// ui-vite/src/pages/Admin/Governance/tabs/SLATab.jsx
/**
 * SLA Tab
 * =======
 * 
 * SLA monitoring dashboard:
 * - Compliance summary
 * - Active violations
 * - Contract status
 * - Historical trends
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
  CircularProgress,
  LinearProgress,
  Alert,
} from '@mui/material';
import {
  Refresh as RefreshIcon,
  Download as DownloadIcon,
} from '@mui/icons-material';

import { governanceApi } from '../../../../services/governanceApi';

// Status chip component
function StatusChip({ status }) {
  const statusConfig = {
    healthy: { color: 'success', label: 'Healthy' },
    at_risk: { color: 'warning', label: 'At Risk' },
    breached: { color: 'error', label: 'Breached' },
  };
  const config = statusConfig[status] || { color: 'default', label: status };
  return <Chip label={config.label} color={config.color} size="small" />;
}

// Severity chip
function SeverityChip({ severity }) {
  const severityConfig = {
    info: { color: 'info', label: 'Info' },
    warning: { color: 'warning', label: 'Warning' },
    critical: { color: 'error', label: 'Critical' },
  };
  const config = severityConfig[severity] || { color: 'default', label: severity };
  return <Chip label={config.label} color={config.color} size="small" />;
}

export default function SLATab({ data }) {
  const [loading, setLoading] = useState(false);
  const [violations, setViolations] = useState([]);
  const [compliance, setCompliance] = useState(null);
  const [contracts, setContracts] = useState([]);
  const [error, setError] = useState(null);

  const fetchSLAData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [violationsRes, complianceRes, contractsRes] = await Promise.all([
        governanceApi.getSLAViolations({ hours: 24 }),
        governanceApi.getSLACompliance(),
        governanceApi.getSLAContracts(),
      ]);
      setViolations(violationsRes || []);
      setCompliance(complianceRes);
      setContracts(contractsRes?.contracts || []);
    } catch (err) {
      setError(err.message || 'Failed to load SLA data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSLAData();
  }, []);

  const handleGenerateReport = async () => {
    try {
      const report = await governanceApi.generateReport({
        report_type: 'weekly_sla',
        formats: ['json', 'csv'],
      });
      alert('Report generated successfully');
    } catch (err) {
      alert('Failed to generate report: ' + err.message);
    }
  };

  return (
    <Box>
      {loading && <LinearProgress sx={{ mb: 2 }} />}
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      <Box sx={{ mb: 2, display: 'flex', justifyContent: 'space-between' }}>
        <Typography variant="h6">SLA Dashboard</Typography>
        <Box>
          <Button
            startIcon={<RefreshIcon />}
            onClick={fetchSLAData}
            disabled={loading}
            sx={{ mr: 1 }}
          >
            Refresh
          </Button>
          <Button
            startIcon={<DownloadIcon />}
            onClick={handleGenerateReport}
            variant="outlined"
          >
            Generate Report
          </Button>
        </Box>
      </Box>

      <Grid container spacing={3}>
        {/* Compliance Summary */}
        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 3 }}>
            <Typography variant="h6" gutterBottom>
              Overall Compliance
            </Typography>
            <Box sx={{ textAlign: 'center', my: 2 }}>
              <Typography variant="h2" color={
                (data?.compliance_rate || 1) >= 0.999 ? 'success.main' :
                (data?.compliance_rate || 1) >= 0.99 ? 'warning.main' : 'error.main'
              }>
                {((data?.compliance_rate || 1) * 100).toFixed(2)}%
              </Typography>
              <StatusChip status={data?.current_status || 'healthy'} />
            </Box>
          </Paper>
        </Grid>

        {/* Quick Stats */}
        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 3 }}>
            <Typography variant="h6" gutterBottom>
              Violation Summary (24h)
            </Typography>
            <Table size="small">
              <TableBody>
                <TableRow>
                  <TableCell>Total Violations</TableCell>
                  <TableCell align="right">{violations.length}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>Critical</TableCell>
                  <TableCell align="right" sx={{ color: 'error.main' }}>
                    {violations.filter(v => v.severity === 'critical').length}
                  </TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>Warning</TableCell>
                  <TableCell align="right" sx={{ color: 'warning.main' }}>
                    {violations.filter(v => v.severity === 'warning').length}
                  </TableCell>
                </TableRow>
                <TableRow>
                  <TableCell>Acknowledged</TableCell>
                  <TableCell align="right">
                    {violations.filter(v => v.acknowledged).length}
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </Paper>
        </Grid>

        {/* Active Contracts */}
        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 3 }}>
            <Typography variant="h6" gutterBottom>
              Active Contracts
            </Typography>
            <Table size="small">
              <TableBody>
                {contracts.slice(0, 5).map((contract) => (
                  <TableRow key={contract.contract_id}>
                    <TableCell>{contract.name}</TableCell>
                    <TableCell align="right">
                      <Chip
                        label={contract.enabled ? 'Active' : 'Disabled'}
                        color={contract.enabled ? 'success' : 'default'}
                        size="small"
                      />
                    </TableCell>
                  </TableRow>
                ))}
                {contracts.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={2} align="center">
                      No contracts configured
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </Paper>
        </Grid>

        {/* Recent Violations */}
        <Grid item xs={12}>
          <Paper sx={{ p: 3 }}>
            <Typography variant="h6" gutterBottom>
              Recent Violations
            </Typography>
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Time</TableCell>
                    <TableCell>Contract</TableCell>
                    <TableCell>Target</TableCell>
                    <TableCell>Metric</TableCell>
                    <TableCell>Value</TableCell>
                    <TableCell>Threshold</TableCell>
                    <TableCell>Severity</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {violations.slice(0, 20).map((violation, idx) => (
                    <TableRow key={idx}>
                      <TableCell>
                        {new Date(violation.timestamp).toLocaleString()}
                      </TableCell>
                      <TableCell>{violation.contract_id}</TableCell>
                      <TableCell>{violation.target_name}</TableCell>
                      <TableCell>{violation.metric}</TableCell>
                      <TableCell>{violation.actual_value?.toFixed(2)}</TableCell>
                      <TableCell>{violation.threshold}</TableCell>
                      <TableCell>
                        <SeverityChip severity={violation.severity} />
                      </TableCell>
                    </TableRow>
                  ))}
                  {violations.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={7} align="center">
                        No violations in the last 24 hours
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          </Paper>
        </Grid>

        {/* Per-Contract Compliance */}
        {compliance && (
          <Grid item xs={12}>
            <Paper sx={{ p: 3 }}>
              <Typography variant="h6" gutterBottom>
                Per-Contract Compliance
              </Typography>
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Contract</TableCell>
                      <TableCell>Status</TableCell>
                      <TableCell>Compliance</TableCell>
                      <TableCell>Violations (24h)</TableCell>
                      <TableCell>Last Evaluation</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {Object.entries(compliance.by_contract || {}).map(([contractId, info]) => (
                      <TableRow key={contractId}>
                        <TableCell>{contractId}</TableCell>
                        <TableCell>
                          <StatusChip status={info.status} />
                        </TableCell>
                        <TableCell>
                          {((info.compliance || 1) * 100).toFixed(2)}%
                        </TableCell>
                        <TableCell>{info.violations_count || 0}</TableCell>
                        <TableCell>
                          {info.last_evaluation
                            ? new Date(info.last_evaluation).toLocaleString()
                            : 'N/A'}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </Paper>
          </Grid>
        )}
      </Grid>
    </Box>
  );
}
