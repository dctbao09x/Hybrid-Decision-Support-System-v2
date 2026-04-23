# backend/ops/governance/approval_workflow.py
"""
Approval Workflow Engine
========================

Manages approval workflows for sensitive operations.

Features:
- Multi-approver support
- Escalation
- Timeout handling
- Audit trail
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger("ops.governance.approval_workflow")


class ApprovalStatus(str, Enum):
    """Status of an approval request."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass
class ApprovalDecision:
    """Record of an approval decision."""
    approver_id: str
    approver_role: str
    decision: str  # approve, reject
    comment: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ApprovalRequest:
    """An approval request for a command."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    
    # Request details
    command_id: str = ""
    command_type: str = ""
    target: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    
    # Requester info
    requester_id: str = ""
    requester_role: str = ""
    reason: Optional[str] = None
    
    # Approval requirements
    required_approvers: int = 1
    allowed_approver_roles: List[str] = field(default_factory=list)
    
    # Status
    status: ApprovalStatus = ApprovalStatus.PENDING
    decisions: List[ApprovalDecision] = field(default_factory=list)
    
    # Timing
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    
    # Escalation
    escalated: bool = False
    escalation_level: int = 0
    
    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def approval_count(self) -> int:
        """Count of approvals."""
        return sum(1 for d in self.decisions if d.decision == "approve")
    
    @property
    def rejection_count(self) -> int:
        """Count of rejections."""
        return sum(1 for d in self.decisions if d.decision == "reject")
    
    @property
    def is_expired(self) -> bool:
        """Check if request has expired."""
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return True
        return False


# Callback types
ApprovalCallback = Callable[[ApprovalRequest, bool], Coroutine[Any, Any, None]]


class ApprovalWorkflow:
    """
    Manages approval workflows.
    
    Features:
    - Request submission
    - Approval/rejection handling
    - Expiration management
    - Notification integration
    """
    
    def __init__(
        self,
        default_expiry_hours: int = 24,
        escalation_hours: int = 4,
    ):
        self._requests: Dict[str, ApprovalRequest] = {}
        self._default_expiry_hours = default_expiry_hours
        self._escalation_hours = escalation_hours
        
        # Callbacks
        self._on_approved: List[ApprovalCallback] = []
        self._on_rejected: List[ApprovalCallback] = []
        self._on_expired: List[ApprovalCallback] = []
    
    def submit(
        self,
        command_id: str,
        command_type: str,
        target: str,
        requester_id: str,
        requester_role: str,
        required_approvers: int = 1,
        allowed_approver_roles: Optional[List[str]] = None,
        reason: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        expiry_hours: Optional[int] = None,
    ) -> ApprovalRequest:
        """
        Submit a new approval request.
        
        Args:
            command_id: ID of the command requiring approval
            command_type: Type of command
            target: Target resource
            requester_id: ID of requester
            requester_role: Role of requester
            required_approvers: Number of approvals needed
            allowed_approver_roles: Roles allowed to approve
            reason: Reason for the action
            params: Command parameters
            expiry_hours: Hours until expiry
            
        Returns:
            Created ApprovalRequest
        """
        hours = expiry_hours or self._default_expiry_hours
        
        request = ApprovalRequest(
            command_id=command_id,
            command_type=command_type,
            target=target,
            requester_id=requester_id,
            requester_role=requester_role,
            required_approvers=required_approvers,
            allowed_approver_roles=allowed_approver_roles or ["admin"],
            reason=reason,
            params=params or {},
            expires_at=datetime.utcnow() + timedelta(hours=hours),
        )
        
        self._requests[request.id] = request
        logger.info(f"Approval request submitted: {request.id} for {command_type}")
        
        return request
    
    def approve(
        self,
        request_id: str,
        approver_id: str,
        approver_role: str,
        comment: Optional[str] = None,
    ) -> ApprovalRequest:
        """
        Approve a request.
        
        Args:
            request_id: ID of the request
            approver_id: ID of approver
            approver_role: Role of approver
            comment: Optional comment
            
        Returns:
            Updated ApprovalRequest
            
        Raises:
            ValueError: If request not found or invalid
        """
        request = self._requests.get(request_id)
        if not request:
            raise ValueError(f"Request {request_id} not found")
        
        if request.status != ApprovalStatus.PENDING:
            raise ValueError(f"Request {request_id} is not pending")
        
        if request.is_expired:
            request.status = ApprovalStatus.EXPIRED
            raise ValueError(f"Request {request_id} has expired")
        
        # Check authorization
        if request.allowed_approver_roles:
            if approver_role not in request.allowed_approver_roles:
                raise ValueError(f"Role {approver_role} not authorized to approve")
        
        # Cannot approve own request
        if approver_id == request.requester_id:
            raise ValueError("Cannot approve own request")
        
        # Check for duplicate approval
        if any(d.approver_id == approver_id for d in request.decisions):
            raise ValueError(f"Approver {approver_id} has already responded")
        
        # Record decision
        decision = ApprovalDecision(
            approver_id=approver_id,
            approver_role=approver_role,
            decision="approve",
            comment=comment,
        )
        request.decisions.append(decision)
        
        # Check if fully approved
        if request.approval_count >= request.required_approvers:
            request.status = ApprovalStatus.APPROVED
            request.resolved_at = datetime.utcnow()
            logger.info(f"Request {request_id} approved")
            
            # Trigger callbacks
            self._trigger_callbacks(request, True)
        
        return request
    
    def reject(
        self,
        request_id: str,
        rejector_id: str,
        rejector_role: str,
        comment: Optional[str] = None,
    ) -> ApprovalRequest:
        """
        Reject a request.
        
        Args:
            request_id: ID of the request
            rejector_id: ID of rejector
            rejector_role: Role of rejector
            comment: Optional comment
            
        Returns:
            Updated ApprovalRequest
        """
        request = self._requests.get(request_id)
        if not request:
            raise ValueError(f"Request {request_id} not found")
        
        if request.status != ApprovalStatus.PENDING:
            raise ValueError(f"Request {request_id} is not pending")
        
        # Record decision
        decision = ApprovalDecision(
            approver_id=rejector_id,
            approver_role=rejector_role,
            decision="reject",
            comment=comment,
        )
        request.decisions.append(decision)
        
        # Any rejection = rejected
        request.status = ApprovalStatus.REJECTED
        request.resolved_at = datetime.utcnow()
        logger.info(f"Request {request_id} rejected")
        
        # Trigger callbacks
        self._trigger_callbacks(request, False)
        
        return request
    
    def cancel(self, request_id: str, canceller_id: str) -> ApprovalRequest:
        """Cancel an approval request."""
        request = self._requests.get(request_id)
        if not request:
            raise ValueError(f"Request {request_id} not found")
        
        if request.status != ApprovalStatus.PENDING:
            raise ValueError(f"Request {request_id} is not pending")
        
        # Only requester or admin can cancel
        if canceller_id != request.requester_id:
            raise ValueError("Only requester can cancel")
        
        request.status = ApprovalStatus.CANCELLED
        request.resolved_at = datetime.utcnow()
        logger.info(f"Request {request_id} cancelled")
        
        return request
    
    def get(self, request_id: str) -> Optional[ApprovalRequest]:
        """Get an approval request by ID."""
        return self._requests.get(request_id)
    
    def get_pending(
        self,
        approver_role: Optional[str] = None,
        requester_id: Optional[str] = None,
    ) -> List[ApprovalRequest]:
        """Get pending approval requests."""
        pending = []
        
        for request in self._requests.values():
            # Check expiry
            if request.is_expired and request.status == ApprovalStatus.PENDING:
                request.status = ApprovalStatus.EXPIRED
                self._trigger_callbacks(request, False)
                continue
            
            if request.status != ApprovalStatus.PENDING:
                continue
            
            if requester_id and request.requester_id != requester_id:
                continue
            
            if approver_role:
                if request.allowed_approver_roles and approver_role not in request.allowed_approver_roles:
                    continue
            
            pending.append(request)
        
        return sorted(pending, key=lambda r: r.created_at, reverse=True)
    
    def get_by_command(self, command_id: str) -> Optional[ApprovalRequest]:
        """Get approval request for a command."""
        for request in self._requests.values():
            if request.command_id == command_id:
                return request
        return None
    
    def check_escalation(self):
        """Check for requests needing escalation."""
        now = datetime.utcnow()
        escalation_threshold = timedelta(hours=self._escalation_hours)
        
        for request in self._requests.values():
            if request.status != ApprovalStatus.PENDING:
                continue
            
            if request.is_expired:
                request.status = ApprovalStatus.EXPIRED
                self._trigger_callbacks(request, False)
                continue
            
            # Check if should escalate
            age = now - request.created_at
            if age > escalation_threshold * (request.escalation_level + 1):
                request.escalated = True
                request.escalation_level += 1
                logger.warning(
                    f"Escalating request {request.id} to level {request.escalation_level}"
                )
    
    def on_approved(self, callback: ApprovalCallback):
        """Register callback for approval."""
        self._on_approved.append(callback)
    
    def on_rejected(self, callback: ApprovalCallback):
        """Register callback for rejection."""
        self._on_rejected.append(callback)
    
    def on_expired(self, callback: ApprovalCallback):
        """Register callback for expiration."""
        self._on_expired.append(callback)
    
    def get_stats(self) -> Dict[str, int]:
        """Get workflow statistics."""
        stats = {
            "total": len(self._requests),
            "pending": 0,
            "approved": 0,
            "rejected": 0,
            "expired": 0,
            "cancelled": 0,
        }
        
        for request in self._requests.values():
            status_key = request.status.value
            if status_key in stats:
                stats[status_key] += 1
        
        return stats
    
    def _trigger_callbacks(self, request: ApprovalRequest, approved: bool):
        """Trigger appropriate callbacks."""
        import asyncio
        
        callbacks = []
        if request.status == ApprovalStatus.APPROVED:
            callbacks = self._on_approved
        elif request.status == ApprovalStatus.REJECTED:
            callbacks = self._on_rejected
        elif request.status == ApprovalStatus.EXPIRED:
            callbacks = self._on_expired
        
        for callback in callbacks:
            try:
                # Schedule callback
                asyncio.create_task(callback(request, approved))
            except Exception as e:
                logger.error(f"Approval callback error: {e}")
