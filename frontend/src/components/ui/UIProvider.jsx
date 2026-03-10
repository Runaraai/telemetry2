import React, { createContext, useCallback, useContext, useMemo, useState } from 'react';
import { Snackbar, Alert, Dialog, DialogTitle, DialogContent, DialogContentText, DialogActions, Button } from '@mui/material';

const UIContext = createContext(null);

export function UIProvider({ children }) {
  const [toast, setToast] = useState(null);
  const [confirmState, setConfirmState] = useState(null);

  const showToast = useCallback(({ message, severity = 'info', duration = 4000 }) => {
    setToast({ message, severity, duration });
  }, []);

  const confirm = useCallback(({ title = 'Are you sure?', description, confirmLabel = 'Confirm', cancelLabel = 'Cancel' }) => {
    return new Promise((resolve) => {
      setConfirmState({
        title,
        description,
        confirmLabel,
        cancelLabel,
        resolve,
      });
    });
  }, []);

  const handleConfirmClose = useCallback((result) => {
    if (confirmState?.resolve) {
      confirmState.resolve(result);
    }
    setConfirmState(null);
  }, [confirmState]);

  const value = useMemo(() => ({
    showToast,
    confirm,
  }), [showToast, confirm]);

  return (
    <UIContext.Provider value={value}>
      {children}

      <Snackbar
        open={Boolean(toast)}
        autoHideDuration={toast?.duration || 4000}
        onClose={() => setToast(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert onClose={() => setToast(null)} severity={toast?.severity || 'info'} sx={{ width: '100%' }}>
          {toast?.message}
        </Alert>
      </Snackbar>

      <Dialog
        open={Boolean(confirmState)}
        onClose={() => handleConfirmClose(false)}
        aria-labelledby="confirm-dialog-title"
      >
        <DialogTitle id="confirm-dialog-title">
          {confirmState?.title || 'Confirm'}
        </DialogTitle>
        {confirmState?.description && (
          <DialogContent>
            <DialogContentText>
              {confirmState.description}
            </DialogContentText>
          </DialogContent>
        )}
        <DialogActions>
          <Button onClick={() => handleConfirmClose(false)} color="inherit">
            {confirmState?.cancelLabel || 'Cancel'}
          </Button>
          <Button onClick={() => handleConfirmClose(true)} color="error" variant="contained">
            {confirmState?.confirmLabel || 'Confirm'}
          </Button>
        </DialogActions>
      </Dialog>
    </UIContext.Provider>
  );
}

export function useUI() {
  const ctx = useContext(UIContext);
  if (!ctx) {
    throw new Error('useUI must be used within UIProvider');
  }
  return ctx;
}
