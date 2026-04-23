// ui-vite/src/pages/Admin/Governance/tabs/AlertsTab.jsx
/**
 * Alerts Tab
 * ==========
 * 
 * Alert management:
 * - Active alerts
 * - Alert history
 * - Alert configuration
 */

import React, { useState, useEffect } from 'react';
import {
  Box,
  Grid,
  Paper,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
  Button,
  IconButton,
  Tooltip,
  LinearProgress,
  Alert,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
} from '@mui/material';
import {
  Refresh as RefreshIcon,
  CheckCircle as AcknowledgeIcon,
  Delete as DismissIcon,
  NotificationsOff as MuteIcon,
} from '@mui/icons-material';

import { governanceApi } from '../../../../services/governanceApi';

// Severity chip component
function SeverityChip({ severity }) {
  const config = {
    critical: { color: 'error', label: 'Critical' },
    warning: { color: 'warning', label: 'Warning' },
    info: { color: 'info', label: 'Info' },
  };
  const { color, label } = config[severity] || config.info;
  return <Chip label={label} color={color} size="small" />;
}

export default function AlertsTab() {
  const [loading, setLoading] = useState(true);
  const [alerts, setAlerts] = useState([]);
  const [error, setError] = useState(null);
  const [selectedAlert, setSelectedAlert] = useState(null);

  const fetchAlerts = async () => {
    setLoading(true);
    setError(null);
    try {
      // Get alerts from audit log (which includes SLA violations and risk events)
      const auditData = await governanceApi.getAuditLog({ hours: 24, limit: 100 });
      
      // Filter for alert-like entries
      const alertEntries = (auditData?.audit_entries || [])
        .filter(entry => 
          entry.type === 'sla_violation' || 
          entry.type === 'mitigation' ||
          (entry.type === 'risk_assessment' && entry.level !== 'low')
        )
        .map((entry, idx) => ({
          id: idx,
          timestamp: entry.timestamp,
          type: entry.type,
          severity: entry.level === 'critical' || entry.level === 'high' ? 'critical' : 
                   entry.level === 'warning' || entry.level === 'medium' ? 'warning' : 'info',
          message: formatAlertMessage(entry),
          details: entry.details,
          acknowledged: false,
        }));
      
      setAlerts(alertEntries);
    } catch (err) {
      setError(err.message || 'Failed to load alerts');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAlerts();
  }, []);

  const handleAcknowledge = (alertId) => {
    setAlerts(prev => prev.map(a => 
      a.id === alertId ? { ...a, acknowledged: true } : a
    ));
  };

  const handleDismiss = (alertId) => {
    setAlerts(prev => prev.filter(a => a.id !== alertId));
  };

  const handleViewDetails = (alert) => {
    setSelectedAlert(alert);
  };

  return (
    <Box>
      {loading && <LinearProgress sx={{ mb: 2 }} />}
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      <Box sx={{ mb: 2, display: 'flex', justifyContent: 'space-between' }}>
        <Typography variant="h6">
          Active Alerts
          {alerts.filter(a => !a.acknowledged).length > 0 && (
            <Chip
              label={alerts.filter(a => !a.acknowledged).length}
              color="error"
              size="small"
              sx={{ ml: 1 }}
            />
          )}
        </Typography>
        <Button
          startIcon={<RefreshIcon />}
          onClick={fetchAlerts}
          disabled={loading}
        >
          Refresh
        </Button>
      </Box>

      <Grid container spacing={3}>
        {/* Alert Summary */}
        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 3 }}>
            <Typography variant="h6" gutterBottom>
              Alert Summary
            </Typography>
            <Table size="small">
              <TableBody>
                <TableRow>
                  <TableCell>Total Alerts</TableCell>
                  <TableCell align="right">{alerts.length}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>Critical</TableCell>
                  <TableCell align="right" sx={{ color: 'error.main' }}>
                    {alerts.filter(a => a.severity === 'critical').length}
                  </TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>Warning</TableCell>
                  <TableCell align="right" sx={{ color: 'warning.main' }}>
                    {alerts.filter(a => a.severity === 'warning').length}
                  </TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>Acknowledged</TableCell>
                  <TableCell align="right">
                    {alerts.filter(a => a.acknowledged).length}
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </Paper>
        </Grid>

        {/* Alert Types */}
        <Grid item xs={12} md={8}>
          <Paper sx={{ p: 3 }}>
            <Typography variant="h6" gutterBottom>
              Alerts by Type
            </Typography>
            <Grid container spacing={2}>
              <Grid item xs={4}>
                <Paper variant="outlined" sx={{ p: 2, textAlign: 'center' }}>
                  <Typography variant="h4" color="error.main">
                    {alerts.filter(a => a.type === 'sla_violation').length}
                  </Typography>
                  <Typography variant="body2">SLA Violations</Typography>
                </Paper>
              </Grid>
              <Grid item xs={4}>
                <Paper variant="outlined" sx={{ p: 2, textAlign: 'center' }}>
                  <Typography variant="h4" color="warning.main">
                    {alerts.filter(a => a.type === 'risk_assessment').length}
                  </Typography>
                  <Typography variant="body2">Risk Events</Typography>
                </Paper>
              </Grid>
              <Grid item xs={4}>
                <Paper variant="outlined" sx={{ p: 2, textAlign: 'center' }}>
                  <Typography variant="h4" color="info.main">
                    {alerts.filter(a => a.type === 'mitigation').length}
                  </Typography>
                  <Typography variant="body2">Mitigations</Typography>
                </Paper>
              </Grid>
            </Grid>
          </Paper>
        </Grid>

        {/* Alert List */}
        <Grid item xs={12}>
          <Paper sx={{ p: 3 }}>
            <Typography variant="h6" gutterBottom>
              Alert History (24h)
            </Typography>
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Time</TableCell>
                    <TableCell>Type</TableCell>
                    <TableCell>Severity</TableCell>
                    <TableCell>Message</TableCell>
                    <TableCell>Status</TableCell>
                    <TableCell>Actions</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {alerts.map((alert) => (
                    <TableRow
                      key={alert.id}
                      sx={{
                        bgcolor: alert.acknowledged ? 'action.hover' : undefined,
                        opacity: alert.acknowledged ? 0.7 : 1,
                      }}
                    >
                      <TableCell>
                        {new Date(alert.timestamp).toLocaleString()}
                      </TableCell>
                      <TableCell sx={{ textTransform: 'capitalize' }}>
                        {alert.type.replace(/_/g, ' ')}
                      </TableCell>
                      <TableCell>
                        <SeverityChip severity={alert.severity} />
                      </TableCell>
                      <TableCell sx={{ maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {alert.message}
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={alert.acknowledged ? 'Acknowledged' : 'Active'}
                          color={alert.acknowledged ? 'default' : 'error'}
                          size="small"
                        />
                      </TableCell>
                      <TableCell>
                        <Tooltip title="Acknowledge">
                          <IconButton
                            size="small"
                            onClick={() => handleAcknowledge(alert.id)}
                            disabled={alert.acknowledged}
                          >
                            <AcknowledgeIcon />
                          </IconButton>
                        </Tooltip>
                        <Tooltip title="View Details">
                          <IconButton
                            size="small"
                            onClick={() => handleViewDetails(alert)}
                          >
                            <MuteIcon />
                          </IconButton>
                        </Tooltip>
                        <Tooltip title="Dismiss">
                          <IconButton
                            size="small"
                            onClick={() => handleDismiss(alert.id)}
                          >
                            <DismissIcon />
                          </IconButton>
                        </Tooltip>
                      </TableCell>
                    </TableRow>
                  ))}
                  {alerts.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={6} align="center">
                        No alerts in the last 24 hours
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          </Paper>
        </Grid>
      </Grid>

      {/* Alert Details Dialog */}
      <Dialog
        open={!!selectedAlert}
        onClose={() => setSelectedAlert(null)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>Alert Details</DialogTitle>
        <DialogContent>
          {selectedAlert && (
            <Box>
              <Typography variant="body2" color="text.secondary" gutterBottom>
                Timestamp: {new Date(selectedAlert.timestamp).toLocaleString()}
              </Typography>
              <Typography variant="body2" color="text.secondary" gutterBottom>
                Type: {selectedAlert.type}
              </Typography>
              <Typography variant="body2" color="text.secondary" gutterBottom>
                Severity: {selectedAlert.severity}
              </Typography>
              <Typography variant="body1" sx={{ mt: 2 }}>
                {selectedAlert.message}
              </Typography>
              <Paper variant="outlined" sx={{ mt: 2, p: 2, bgcolor: 'grey.100' }}>
                <Typography variant="caption">Raw Details:</Typography>
                <pre style={{ margin: 0, fontSize: '0.75rem', overflow: 'auto' }}>
                  {JSON.stringify(selectedAlert.details, null, 2)}
                </pre>
              </Paper>
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSelectedAlert(null)}>Close</Button>
          {selectedAlert && !selectedAlert.acknowledged && (
            <Button
              onClick={() => {
                handleAcknowledge(selectedAlert.id);
                setSelectedAlert(null);
              }}
              color="primary"
            >
              Acknowledge
            </Button>
          )}
        </DialogActions>
      </Dialog>
    </Box>
  );
}

// Helper function to format alert messages
function formatAlertMessage(entry) {
  switch (entry.type) {
    case 'sla_violation':
      return `SLA violation: ${entry.details?.target_name || 'Unknown'} exceeded threshold`;
    case 'risk_assessment':
      return `Risk level ${entry.level}: score ${(entry.details?.score * 100 || 0).toFixed(1)}%`;
    case 'mitigation':
      return `Mitigation ${entry.details?.status}: ${entry.details?.action_name || 'Unknown action'}`;
    default:
      return `${entry.type}: ${entry.level}`;
  }
}
