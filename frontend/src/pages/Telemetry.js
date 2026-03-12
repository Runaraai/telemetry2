import React, { useState, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Box } from '@mui/material';
import TelemetryTab from '../components/TelemetryTab';

export default function Telemetry() {
  const location = useLocation();
  const navigate = useNavigate();
  const [instanceData, setInstanceData] = useState(null);

  useEffect(() => {
    const state = location.state;
    if (state?.instanceData) {
      setInstanceData(state.instanceData);
    }
  }, [location.state]);

  return (
    <Box>
      <TelemetryTab
        instanceData={instanceData}
        onNavigateToInstances={() => navigate('/instances')}
      />
    </Box>
  );
}
