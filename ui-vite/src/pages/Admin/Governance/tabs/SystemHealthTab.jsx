// ui-vite/src/pages/Admin/Governance/tabs/SystemHealthTab.jsx
/**
 * System Health Tab
 * =================
 * 
 * Displays overall system health metrics:
 * - Risk score and components
 * - Performance metrics
 * - Resource utilization
 */

import React from 'react';
import {
  Box,
  Grid,
  Paper,
  Typography,
  LinearProgress,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
} from '@mui/material';

// Risk level colors
const riskColors = {
  low: '#4caf50',
  medium: '#ff9800',
  high: '#f44336',
  critical: '#d32f2f',
};

// Progress bar for risk components
function RiskComponent({ name, value, maxValue = 1 }) {
  const percentage = (value / maxValue) * 100;
  const color = percentage > 70 ? 'error' : percentage > 40 ? 'warning' : 'success';

  return (
    <Box sx={{ mb: 2 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
        <Typography variant="body2">{name}</Typography>
        <Typography variant="body2">{(value * 100).toFixed(1)}%</Typography>
      </Box>
      <LinearProgress
        variant="determinate"
        value={Math.min(percentage, 100)}
        color={color}
        sx={{ height: 8, borderRadius: 4 }}
      />
    </Box>
  );
}

// Metric card
function MetricCard({ title, value, unit, status }) {
  return (
    <Paper sx={{ p: 2, height: '100%' }}>
      <Typography color="text.secondary" variant="caption">
        {title}
      </Typography>
      <Typography variant="h4" component="div">
        {value}
        <Typography component="span" variant="body2" color="text.secondary">
          {unit}
        </Typography>
      </Typography>
      {status && (
        <Chip
          label={status}
          size="small"
          color={status === 'normal' ? 'success' : status === 'warning' ? 'warning' : 'error'}
          sx={{ mt: 1 }}
        />
      )}
    </Paper>
  );
}

export default function SystemHealthTab({ data, onRefresh }) {
  const riskData = data?.risk?.dashboard || {};
  const slaMetrics = data?.sla_metrics || {};
  const aggregator = data?.aggregator || {};

  const currentRisk = riskData.current_risk || {};
  const avgComponents = riskData.average_components || {};

  return (
    <Box>
      <Grid container spacing={3}>
        {/* Risk Overview */}
        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 3, height: '100%' }}>
            <Typography variant="h6" gutterBottom>
              Risk Score
            </Typography>
            <Box sx={{ textAlign: 'center', my: 2 }}>
              <Typography
                variant="h2"
                sx={{
                  color: riskColors[currentRisk.level] || '#9e9e9e',
                  fontWeight: 'bold',
                }}
              >
                {currentRisk.score !== undefined
                  ? (currentRisk.score * 100).toFixed(0)
                  : 'N/A'}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Current Risk Score
              </Typography>
              <Chip
                label={currentRisk.level?.toUpperCase() || 'UNKNOWN'}
                sx={{
                  mt: 1,
                  bgcolor: riskColors[currentRisk.level] || '#9e9e9e',
                  color: 'white',
                }}
              />
            </Box>
          </Paper>
        </Grid>

        {/* Risk Components */}
        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 3, height: '100%' }}>
            <Typography variant="h6" gutterBottom>
              Risk Components
            </Typography>
            <RiskComponent name="Drift" value={avgComponents.drift || 0} />
            <RiskComponent name="Latency" value={avgComponents.latency || 0} />
            <RiskComponent name="Error Rate" value={avgComponents.error_rate || 0} />
            <RiskComponent name="Cost Overrun" value={avgComponents.cost_overrun || 0} />
          </Paper>
        </Grid>

        {/* Risk Distribution */}
        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 3, height: '100%' }}>
            <Typography variant="h6" gutterBottom>
              Risk Distribution (24h)
            </Typography>
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Level</TableCell>
                    <TableCell align="right">Count</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {Object.entries(riskData.level_distribution || {}).map(([level, count]) => (
                    <TableRow key={level}>
                      <TableCell>
                        <Chip
                          label={level.toUpperCase()}
                          size="small"
                          sx={{
                            bgcolor: riskColors[level] || '#9e9e9e',
                            color: 'white',
                          }}
                        />
                      </TableCell>
                      <TableCell align="right">{count}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Paper>
        </Grid>

        {/* SLA Metrics */}
        <Grid item xs={12} sm={6} md={3}>
          <MetricCard
            title="Total Requests (24h)"
            value={slaMetrics.total_requests || 0}
            unit=""
            status="normal"
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <MetricCard
            title="Error Rate"
            value={((slaMetrics.error_rate || 0) * 100).toFixed(2)}
            unit="%"
            status={(slaMetrics.error_rate || 0) > 0.05 ? 'error' : 'normal'}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <MetricCard
            title="Avg Latency"
            value={(slaMetrics.avg_latency_ms || 0).toFixed(0)}
            unit="ms"
            status={(slaMetrics.avg_latency_ms || 0) > 500 ? 'warning' : 'normal'}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <MetricCard
            title="P95 Latency"
            value={(slaMetrics.p95_latency_ms || 0).toFixed(0)}
            unit="ms"
            status={(slaMetrics.p95_latency_ms || 0) > 1000 ? 'warning' : 'normal'}
          />
        </Grid>

        {/* Mitigations */}
        <Grid item xs={12}>
          <Paper sx={{ p: 3 }}>
            <Typography variant="h6" gutterBottom>
              Recent Mitigations
            </Typography>
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Action</TableCell>
                    <TableCell>Triggered At</TableCell>
                    <TableCell>Risk Level</TableCell>
                    <TableCell>Status</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {(riskData.mitigation_events || []).slice(0, 10).map((event, idx) => (
                    <TableRow key={idx}>
                      <TableCell>{event.action_name}</TableCell>
                      <TableCell>
                        {new Date(event.triggered_at).toLocaleString()}
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={event.risk_level?.toUpperCase()}
                          size="small"
                          sx={{
                            bgcolor: riskColors[event.risk_level] || '#9e9e9e',
                            color: 'white',
                          }}
                        />
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={event.status}
                          size="small"
                          color={event.status === 'completed' ? 'success' : 'error'}
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                  {(!riskData.mitigation_events || riskData.mitigation_events.length === 0) && (
                    <TableRow>
                      <TableCell colSpan={4} align="center">
                        No recent mitigations
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          </Paper>
        </Grid>
      </Grid>
    </Box>
  );
}
