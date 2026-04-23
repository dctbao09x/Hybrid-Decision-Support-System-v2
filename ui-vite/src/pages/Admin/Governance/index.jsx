// ui-vite/src/pages/Admin/Governance/index.jsx
/**
 * Governance Admin Panel
 * ======================
 * 
 * Main admin panel for OPS / Governance Platform with tabs:
 * - System Health
 * - SLA Dashboard  
 * - Drift Monitor
 * - Cost Tracking
 * - Alerts
 * - Audit Log
 */

import React, { useState, useEffect, useCallback } from 'react';
import {
  Box,
  Container,
  Typography,
  Tabs,
  Tab,
  Paper,
  Grid,
  Card,
  CardContent,
  Chip,
  Alert,
  CircularProgress,
  IconButton,
  Tooltip,
  LinearProgress,
} from '@mui/material';
import {
  Refresh as RefreshIcon,
  HealthAndSafety as HealthIcon,
  Speed as SpeedIcon,
  Timeline as TimelineIcon,
  AttachMoney as CostIcon,
  NotificationsActive as AlertIcon,
  History as AuditIcon,
  Warning as WarningIcon,
  CheckCircle as CheckCircleIcon,
  Error as ErrorIcon,
} from '@mui/icons-material';

// Tab components
import SystemHealthTab from './tabs/SystemHealthTab';
import SLATab from './tabs/SLATab';
import DriftTab from './tabs/DriftTab';
import CostTab from './tabs/CostTab';
import AlertsTab from './tabs/AlertsTab';
import AuditTab from './tabs/AuditTab';

// API service
import { governanceApi } from '../../../services/governanceApi';

// Tab panel component
function TabPanel({ children, value, index, ...other }) {
  return (
    <div
      role="tabpanel"
      hidden={value !== index}
      id={`governance-tabpanel-${index}`}
      aria-labelledby={`governance-tab-${index}`}
      {...other}
    >
      {value === index && <Box sx={{ py: 3 }}>{children}</Box>}
    </div>
  );
}

function a11yProps(index) {
  return {
    id: `governance-tab-${index}`,
    'aria-controls': `governance-tabpanel-${index}`,
  };
}

// Status indicator component
function StatusIndicator({ status }) {
  const statusConfig = {
    healthy: { color: 'success', icon: <CheckCircleIcon />, label: 'Healthy' },
    at_risk: { color: 'warning', icon: <WarningIcon />, label: 'At Risk' },
    breached: { color: 'error', icon: <ErrorIcon />, label: 'Breached' },
    unknown: { color: 'default', icon: null, label: 'Unknown' },
  };

  const config = statusConfig[status] || statusConfig.unknown;

  return (
    <Chip
      icon={config.icon}
      label={config.label}
      color={config.color}
      size="small"
    />
  );
}

// Main Governance Panel component
export default function GovernancePanel() {
  const [activeTab, setActiveTab] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [dashboardData, setDashboardData] = useState(null);
  const [lastRefresh, setLastRefresh] = useState(null);

  const fetchDashboard = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await governanceApi.getDashboard();
      setDashboardData(data);
      setLastRefresh(new Date());
    } catch (err) {
      setError(err.message || 'Failed to load dashboard');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchDashboard();
    // Auto-refresh every 30 seconds
    const interval = setInterval(fetchDashboard, 30000);
    return () => clearInterval(interval);
  }, [fetchDashboard]);

  const handleTabChange = (event, newValue) => {
    setActiveTab(newValue);
  };

  const handleRefresh = () => {
    fetchDashboard();
  };

  // Calculate overall status
  const getOverallStatus = () => {
    if (!dashboardData) return 'unknown';
    
    const riskLevel = dashboardData.risk?.current_level;
    const slaStatus = dashboardData.sla?.current_status;
    
    if (riskLevel === 'critical' || slaStatus === 'breached') return 'breached';
    if (riskLevel === 'high' || slaStatus === 'at_risk') return 'at_risk';
    return 'healthy';
  };

  return (
    <Container maxWidth="xl" sx={{ py: 4 }}>
      {/* Header */}
      <Box sx={{ mb: 4, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Box>
          <Typography variant="h4" component="h1" gutterBottom>
            Governance Platform
          </Typography>
          <Typography variant="body2" color="text.secondary">
            OPS / SLA / Risk / Cost Monitoring Dashboard
            {lastRefresh && (
              <span> • Last updated: {lastRefresh.toLocaleTimeString()}</span>
            )}
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <StatusIndicator status={getOverallStatus()} />
          <Tooltip title="Refresh">
            <IconButton onClick={handleRefresh} disabled={loading}>
              <RefreshIcon />
            </IconButton>
          </Tooltip>
        </Box>
      </Box>

      {/* Loading indicator */}
      {loading && <LinearProgress sx={{ mb: 2 }} />}

      {/* Error alert */}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {/* Quick Stats */}
      {dashboardData && (
        <Grid container spacing={2} sx={{ mb: 3 }}>
          <Grid item xs={12} sm={6} md={3}>
            <Card>
              <CardContent>
                <Typography color="text.secondary" gutterBottom>
                  Risk Level
                </Typography>
                <Typography variant="h5">
                  {dashboardData.risk?.current_level?.toUpperCase() || 'N/A'}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} sm={6} md={3}>
            <Card>
              <CardContent>
                <Typography color="text.secondary" gutterBottom>
                  SLA Compliance
                </Typography>
                <Typography variant="h5">
                  {((dashboardData.sla?.compliance_rate || 1) * 100).toFixed(1)}%
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} sm={6} md={3}>
            <Card>
              <CardContent>
                <Typography color="text.secondary" gutterBottom>
                  Active Violations
                </Typography>
                <Typography variant="h5" color="error.main">
                  {dashboardData.sla?.active_violations || 0}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} sm={6} md={3}>
            <Card>
              <CardContent>
                <Typography color="text.secondary" gutterBottom>
                  Uptime (24h)
                </Typography>
                <Typography variant="h5" color="success.main">
                  {((dashboardData.sla_metrics?.uptime || 1) * 100).toFixed(2)}%
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      )}

      {/* Main Tabs */}
      <Paper sx={{ width: '100%' }}>
        <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
          <Tabs
            value={activeTab}
            onChange={handleTabChange}
            aria-label="governance tabs"
            variant="scrollable"
            scrollButtons="auto"
          >
            <Tab
              icon={<HealthIcon />}
              iconPosition="start"
              label="System Health"
              {...a11yProps(0)}
            />
            <Tab
              icon={<SpeedIcon />}
              iconPosition="start"
              label="SLA"
              {...a11yProps(1)}
            />
            <Tab
              icon={<TimelineIcon />}
              iconPosition="start"
              label="Drift"
              {...a11yProps(2)}
            />
            <Tab
              icon={<CostIcon />}
              iconPosition="start"
              label="Cost"
              {...a11yProps(3)}
            />
            <Tab
              icon={<AlertIcon />}
              iconPosition="start"
              label="Alerts"
              {...a11yProps(4)}
            />
            <Tab
              icon={<AuditIcon />}
              iconPosition="start"
              label="Audit"
              {...a11yProps(5)}
            />
          </Tabs>
        </Box>

        <TabPanel value={activeTab} index={0}>
          <SystemHealthTab data={dashboardData} onRefresh={handleRefresh} />
        </TabPanel>
        <TabPanel value={activeTab} index={1}>
          <SLATab data={dashboardData?.sla} />
        </TabPanel>
        <TabPanel value={activeTab} index={2}>
          <DriftTab />
        </TabPanel>
        <TabPanel value={activeTab} index={3}>
          <CostTab data={dashboardData?.aggregator} />
        </TabPanel>
        <TabPanel value={activeTab} index={4}>
          <AlertsTab />
        </TabPanel>
        <TabPanel value={activeTab} index={5}>
          <AuditTab />
        </TabPanel>
      </Paper>
    </Container>
  );
}
