// ui-vite/src/pages/Admin/Governance/tabs/CostTab.jsx
/**
 * Cost Tab
 * ========
 * 
 * Cost tracking and budget monitoring:
 * - Total costs by category
 * - Cost trends
 * - Budget alerts
 */

import React from 'react';
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
  LinearProgress,
  Chip,
} from '@mui/material';

// Cost breakdown bar
function CostBar({ label, value, total, color = 'primary' }) {
  const percentage = total > 0 ? (value / total) * 100 : 0;
  
  return (
    <Box sx={{ mb: 2 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
        <Typography variant="body2">{label}</Typography>
        <Typography variant="body2">${value.toFixed(2)}</Typography>
      </Box>
      <LinearProgress
        variant="determinate"
        value={percentage}
        color={color}
        sx={{ height: 8, borderRadius: 4 }}
      />
    </Box>
  );
}

export default function CostTab({ data }) {
  const costBreakdown = data?.cost_breakdown || {};
  const dashboard = data || {};

  // Calculate totals
  const totalCost = Object.values(costBreakdown).reduce((sum, val) => sum + (val || 0), 0);
  
  // Mock budget data (would come from config in production)
  const budget = {
    daily: 100,
    monthly: 2500,
    current_daily: totalCost,
    current_monthly: totalCost * 30, // Rough estimate
  };

  const budgetUtilization = budget.daily > 0 ? (budget.current_daily / budget.daily) * 100 : 0;

  return (
    <Box>
      <Grid container spacing={3}>
        {/* Cost Overview */}
        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 3 }}>
            <Typography variant="h6" gutterBottom>
              Daily Cost
            </Typography>
            <Box sx={{ textAlign: 'center', my: 2 }}>
              <Typography variant="h2" color={
                budgetUtilization > 100 ? 'error.main' :
                budgetUtilization > 80 ? 'warning.main' : 'success.main'
              }>
                ${totalCost.toFixed(2)}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Budget: ${budget.daily.toFixed(2)} / day
              </Typography>
              <Chip
                label={`${budgetUtilization.toFixed(0)}% utilized`}
                color={
                  budgetUtilization > 100 ? 'error' :
                  budgetUtilization > 80 ? 'warning' : 'success'
                }
                sx={{ mt: 2 }}
              />
            </Box>
          </Paper>
        </Grid>

        {/* Cost Breakdown */}
        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 3 }}>
            <Typography variant="h6" gutterBottom>
              Cost Breakdown
            </Typography>
            <CostBar 
              label="LLM Inference" 
              value={costBreakdown.llm || 0} 
              total={totalCost}
              color="primary"
            />
            <CostBar 
              label="Embedding" 
              value={costBreakdown.embedding || 0} 
              total={totalCost}
              color="secondary"
            />
            <CostBar 
              label="Compute" 
              value={costBreakdown.compute || 0} 
              total={totalCost}
              color="info"
            />
            <CostBar 
              label="Storage" 
              value={costBreakdown.storage || 0} 
              total={totalCost}
              color="warning"
            />
          </Paper>
        </Grid>

        {/* Budget Status */}
        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 3 }}>
            <Typography variant="h6" gutterBottom>
              Budget Status
            </Typography>
            <Box sx={{ mb: 2 }}>
              <Typography variant="body2" color="text.secondary">
                Daily Budget
              </Typography>
              <LinearProgress
                variant="determinate"
                value={Math.min(budgetUtilization, 100)}
                color={budgetUtilization > 100 ? 'error' : budgetUtilization > 80 ? 'warning' : 'success'}
                sx={{ height: 12, borderRadius: 6, mt: 1 }}
              />
              <Typography variant="caption" color="text.secondary">
                ${budget.current_daily.toFixed(2)} / ${budget.daily.toFixed(2)}
              </Typography>
            </Box>
            <Box>
              <Typography variant="body2" color="text.secondary">
                Monthly Projection
              </Typography>
              <LinearProgress
                variant="determinate"
                value={Math.min((budget.current_monthly / budget.monthly) * 100, 100)}
                color={(budget.current_monthly / budget.monthly) > 1 ? 'error' : 'primary'}
                sx={{ height: 12, borderRadius: 6, mt: 1 }}
              />
              <Typography variant="caption" color="text.secondary">
                ${budget.current_monthly.toFixed(2)} / ${budget.monthly.toFixed(2)} (projected)
              </Typography>
            </Box>
          </Paper>
        </Grid>

        {/* Cost Details Table */}
        <Grid item xs={12}>
          <Paper sx={{ p: 3 }}>
            <Typography variant="h6" gutterBottom>
              Cost Details
            </Typography>
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Category</TableCell>
                    <TableCell align="right">Cost ($)</TableCell>
                    <TableCell align="right">% of Total</TableCell>
                    <TableCell align="right">Trend</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {Object.entries(costBreakdown).map(([category, cost]) => (
                    <TableRow key={category}>
                      <TableCell sx={{ textTransform: 'capitalize' }}>
                        {category.replace(/_/g, ' ')}
                      </TableCell>
                      <TableCell align="right">${(cost || 0).toFixed(2)}</TableCell>
                      <TableCell align="right">
                        {totalCost > 0 ? ((cost / totalCost) * 100).toFixed(1) : 0}%
                      </TableCell>
                      <TableCell align="right">
                        <Chip
                          label="Stable"
                          size="small"
                          color="default"
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                  <TableRow sx={{ bgcolor: 'action.hover' }}>
                    <TableCell><strong>Total</strong></TableCell>
                    <TableCell align="right"><strong>${totalCost.toFixed(2)}</strong></TableCell>
                    <TableCell align="right"><strong>100%</strong></TableCell>
                    <TableCell />
                  </TableRow>
                </TableBody>
              </Table>
            </TableContainer>
          </Paper>
        </Grid>

        {/* Cost Optimization Tips */}
        <Grid item xs={12}>
          <Paper sx={{ p: 3, bgcolor: 'info.light', color: 'info.contrastText' }}>
            <Typography variant="h6" gutterBottom>
              Cost Optimization Recommendations
            </Typography>
            <Typography variant="body2">
              • Enable response caching to reduce duplicate LLM calls<br />
              • Use smaller models for simple queries (model routing)<br />
              • Batch requests where possible to improve throughput<br />
              • Review and optimize high-cost queries
            </Typography>
          </Paper>
        </Grid>
      </Grid>
    </Box>
  );
}
