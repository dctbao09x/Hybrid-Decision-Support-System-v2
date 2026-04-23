// ui-vite/src/pages/Admin/Governance/tabs/AuditTab.jsx
/**
 * Audit Tab
 * =========
 * 
 * Audit log viewer:
 * - Event history
 * - Filter by type/severity
 * - Export capability
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
  TablePagination,
  Chip,
  Button,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  LinearProgress,
  Alert,
  IconButton,
  Collapse,
} from '@mui/material';
import {
  Refresh as RefreshIcon,
  Download as DownloadIcon,
  KeyboardArrowDown as ExpandIcon,
  KeyboardArrowUp as CollapseIcon,
} from '@mui/icons-material';

import { governanceApi } from '../../../../services/governanceApi';

// Expandable row component
function AuditRow({ entry }) {
  const [open, setOpen] = useState(false);

  const severityConfig = {
    critical: 'error',
    high: 'error',
    warning: 'warning',
    medium: 'warning',
    low: 'success',
    info: 'info',
  };

  return (
    <>
      <TableRow sx={{ '& > *': { borderBottom: 'unset' } }}>
        <TableCell>
          <IconButton size="small" onClick={() => setOpen(!open)}>
            {open ? <CollapseIcon /> : <ExpandIcon />}
          </IconButton>
        </TableCell>
        <TableCell>
          {new Date(entry.timestamp).toLocaleString()}
        </TableCell>
        <TableCell sx={{ textTransform: 'capitalize' }}>
          {entry.type.replace(/_/g, ' ')}
        </TableCell>
        <TableCell>
          <Chip
            label={entry.level}
            color={severityConfig[entry.level] || 'default'}
            size="small"
          />
        </TableCell>
        <TableCell sx={{ maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {formatSummary(entry)}
        </TableCell>
      </TableRow>
      <TableRow>
        <TableCell style={{ paddingBottom: 0, paddingTop: 0 }} colSpan={5}>
          <Collapse in={open} timeout="auto" unmountOnExit>
            <Box sx={{ margin: 2 }}>
              <Typography variant="subtitle2" gutterBottom>
                Details
              </Typography>
              <Paper variant="outlined" sx={{ p: 2, bgcolor: 'grey.50' }}>
                <pre style={{ margin: 0, fontSize: '0.75rem', overflow: 'auto' }}>
                  {JSON.stringify(entry.details, null, 2)}
                </pre>
              </Paper>
            </Box>
          </Collapse>
        </TableCell>
      </TableRow>
    </>
  );
}

// Format entry summary
function formatSummary(entry) {
  const details = entry.details || {};
  switch (entry.type) {
    case 'risk_assessment':
      return `Risk score: ${(details.score * 100 || 0).toFixed(1)}%`;
    case 'sla_violation':
      return `${details.target_name || 'Unknown'}: ${details.actual_value?.toFixed(2)} > ${details.threshold}`;
    case 'mitigation':
      return `${details.action_name || 'Unknown'}: ${details.status}`;
    default:
      return entry.level;
  }
}

export default function AuditTab() {
  const [loading, setLoading] = useState(true);
  const [auditData, setAuditData] = useState([]);
  const [filteredData, setFilteredData] = useState([]);
  const [error, setError] = useState(null);
  
  // Filters
  const [typeFilter, setTypeFilter] = useState('');
  const [levelFilter, setLevelFilter] = useState('');
  const [hoursFilter, setHoursFilter] = useState(24);
  
  // Pagination
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(25);

  const fetchAuditLog = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await governanceApi.getAuditLog({ hours: hoursFilter, limit: 1000 });
      setAuditData(data?.audit_entries || []);
    } catch (err) {
      setError(err.message || 'Failed to load audit log');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAuditLog();
  }, [hoursFilter]);

  // Apply filters
  useEffect(() => {
    let filtered = auditData;
    
    if (typeFilter) {
      filtered = filtered.filter(e => e.type === typeFilter);
    }
    
    if (levelFilter) {
      filtered = filtered.filter(e => e.level === levelFilter);
    }
    
    setFilteredData(filtered);
    setPage(0);
  }, [auditData, typeFilter, levelFilter]);

  // Get unique types and levels
  const types = [...new Set(auditData.map(e => e.type))];
  const levels = [...new Set(auditData.map(e => e.level))];

  const handleExport = () => {
    const csv = [
      ['Timestamp', 'Type', 'Level', 'Summary', 'Details'],
      ...filteredData.map(e => [
        e.timestamp,
        e.type,
        e.level,
        formatSummary(e),
        JSON.stringify(e.details),
      ]),
    ].map(row => row.join(',')).join('\n');

    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `audit_log_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
  };

  return (
    <Box>
      {loading && <LinearProgress sx={{ mb: 2 }} />}
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      <Box sx={{ mb: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Typography variant="h6">
          Audit Log ({filteredData.length} entries)
        </Typography>
        <Box>
          <Button
            startIcon={<RefreshIcon />}
            onClick={fetchAuditLog}
            disabled={loading}
            sx={{ mr: 1 }}
          >
            Refresh
          </Button>
          <Button
            startIcon={<DownloadIcon />}
            onClick={handleExport}
            variant="outlined"
            disabled={filteredData.length === 0}
          >
            Export CSV
          </Button>
        </Box>
      </Box>

      {/* Filters */}
      <Paper sx={{ p: 2, mb: 3 }}>
        <Grid container spacing={2} alignItems="center">
          <Grid item xs={12} sm={4} md={3}>
            <FormControl fullWidth size="small">
              <InputLabel>Time Range</InputLabel>
              <Select
                value={hoursFilter}
                onChange={(e) => setHoursFilter(e.target.value)}
                label="Time Range"
              >
                <MenuItem value={1}>Last 1 hour</MenuItem>
                <MenuItem value={6}>Last 6 hours</MenuItem>
                <MenuItem value={24}>Last 24 hours</MenuItem>
                <MenuItem value={72}>Last 3 days</MenuItem>
                <MenuItem value={168}>Last 7 days</MenuItem>
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12} sm={4} md={3}>
            <FormControl fullWidth size="small">
              <InputLabel>Event Type</InputLabel>
              <Select
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
                label="Event Type"
              >
                <MenuItem value="">All Types</MenuItem>
                {types.map(type => (
                  <MenuItem key={type} value={type} sx={{ textTransform: 'capitalize' }}>
                    {type.replace(/_/g, ' ')}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12} sm={4} md={3}>
            <FormControl fullWidth size="small">
              <InputLabel>Severity</InputLabel>
              <Select
                value={levelFilter}
                onChange={(e) => setLevelFilter(e.target.value)}
                label="Severity"
              >
                <MenuItem value="">All Levels</MenuItem>
                {levels.map(level => (
                  <MenuItem key={level} value={level}>
                    {level}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12} sm={12} md={3}>
            <Button
              variant="text"
              onClick={() => {
                setTypeFilter('');
                setLevelFilter('');
              }}
              disabled={!typeFilter && !levelFilter}
            >
              Clear Filters
            </Button>
          </Grid>
        </Grid>
      </Paper>

      {/* Audit Table */}
      <Paper>
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell width={50} />
                <TableCell>Timestamp</TableCell>
                <TableCell>Type</TableCell>
                <TableCell>Level</TableCell>
                <TableCell>Summary</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {filteredData
                .slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage)
                .map((entry, idx) => (
                  <AuditRow key={idx} entry={entry} />
                ))}
              {filteredData.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} align="center">
                    No audit entries found
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
        <TablePagination
          rowsPerPageOptions={[10, 25, 50, 100]}
          component="div"
          count={filteredData.length}
          rowsPerPage={rowsPerPage}
          page={page}
          onPageChange={(e, newPage) => setPage(newPage)}
          onRowsPerPageChange={(e) => {
            setRowsPerPage(parseInt(e.target.value, 10));
            setPage(0);
          }}
        />
      </Paper>
    </Box>
  );
}
