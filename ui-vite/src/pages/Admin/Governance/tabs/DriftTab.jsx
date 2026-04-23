// ui-vite/src/pages/Admin/Governance/tabs/DriftTab.jsx
/**
 * Drift Tab
 * =========
 * 
 * Model drift monitoring:
 * - Current drift score
 * - Historical drift trends
 * - Feature drift breakdown
 */

import React, { useState, useEffect } from 'react';
import {
  Box,
  Grid,
  Paper,
  Typography,
  LinearProgress,
  Alert,
  Chip,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
} from '@mui/material';

import { governanceApi } from '../../../../services/governanceApi';

// Drift indicator with color coding
function DriftIndicator({ value, threshold = 0.1 }) {
  const percentage = value * 100;
  const status = value > threshold ? 'error' : value > threshold * 0.7 ? 'warning' : 'success';
  
  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
        <Typography variant="body2">Drift Score</Typography>
        <Typography variant="body2" color={`${status}.main`}>
          {percentage.toFixed(2)}%
        </Typography>
      </Box>
      <LinearProgress
        variant="determinate"
        value={Math.min(percentage * 10, 100)} // Scale for visibility
        color={status}
        sx={{ height: 8, borderRadius: 4 }}
      />
    </Box>
  );
}

export default function DriftTab() {
  const [loading, setLoading] = useState(true);
  const [driftData, setDriftData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchDrift = async () => {
      setLoading(true);
      try {
        const data = await governanceApi.getDrift();
        setDriftData(data);
      } catch (err) {
        setError(err.message || 'Failed to load drift data');
      } finally {
        setLoading(false);
      }
    };
    fetchDrift();
  }, []);

  if (loading) {
    return <LinearProgress />;
  }

  if (error) {
    return <Alert severity="error">{error}</Alert>;
  }

  return (
    <Box>
      <Grid container spacing={3}>
        {/* Current Drift Status */}
        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 3 }}>
            <Typography variant="h6" gutterBottom>
              Current Drift Status
            </Typography>
            <Box sx={{ textAlign: 'center', my: 2 }}>
              <Typography variant="h2" color={
                (driftData?.current_drift || 0) > 0.1 ? 'error.main' :
                (driftData?.current_drift || 0) > 0.07 ? 'warning.main' : 'success.main'
              }>
                {((driftData?.current_drift || 0) * 100).toFixed(1)}%
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Threshold: {((driftData?.threshold || 0.1) * 100).toFixed(0)}%
              </Typography>
              <Chip
                label={driftData?.status || 'monitoring'}
                color={(driftData?.current_drift || 0) > 0.1 ? 'error' : 'success'}
                sx={{ mt: 2 }}
              />
            </Box>
          </Paper>
        </Grid>

        {/* Drift Components */}
        <Grid item xs={12} md={8}>
          <Paper sx={{ p: 3 }}>
            <Typography variant="h6" gutterBottom>
              Drift Components
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Feature-level drift analysis
            </Typography>
            <DriftIndicator 
              value={driftData?.current_drift || 0} 
              threshold={driftData?.threshold || 0.1} 
            />
            <Box sx={{ mt: 2 }}>
              <Typography variant="body2" color="text.secondary">
                Last Check: {driftData?.last_check 
                  ? new Date(driftData.last_check).toLocaleString() 
                  : 'N/A'}
              </Typography>
            </Box>
          </Paper>
        </Grid>

        {/* Drift Alerts */}
        <Grid item xs={12}>
          <Paper sx={{ p: 3 }}>
            <Typography variant="h6" gutterBottom>
              Drift Alerts
            </Typography>
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Time</TableCell>
                    <TableCell>Type</TableCell>
                    <TableCell>Drift Score</TableCell>
                    <TableCell>Threshold</TableCell>
                    <TableCell>Status</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {(driftData?.alerts || []).map((alert, idx) => (
                    <TableRow key={idx}>
                      <TableCell>
                        {new Date(alert.timestamp).toLocaleString()}
                      </TableCell>
                      <TableCell>{alert.type}</TableCell>
                      <TableCell>{(alert.drift_score * 100).toFixed(2)}%</TableCell>
                      <TableCell>{(alert.threshold * 100).toFixed(0)}%</TableCell>
                      <TableCell>
                        <Chip
                          label={alert.status}
                          size="small"
                          color={alert.status === 'resolved' ? 'success' : 'error'}
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                  {(!driftData?.alerts || driftData.alerts.length === 0) && (
                    <TableRow>
                      <TableCell colSpan={5} align="center">
                        No drift alerts
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          </Paper>
        </Grid>

        {/* Best Practices */}
        <Grid item xs={12}>
          <Alert severity="info">
            <Typography variant="subtitle2">Drift Monitoring Best Practices</Typography>
            <Typography variant="body2">
              • Monitor drift regularly (recommended: daily checks)<br />
              • Retrain model when drift exceeds threshold for extended periods<br />
              • Investigate feature-level drift to identify root causes<br />
              • Consider concept drift vs. data drift for appropriate remediation
            </Typography>
          </Alert>
        </Grid>
      </Grid>
    </Box>
  );
}
