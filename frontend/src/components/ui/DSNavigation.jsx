import React from 'react';
import { Box, Typography, Button } from '@mui/material';
import { Link, useLocation } from 'react-router-dom';

/**
 * Design System Sidebar — primary dashboard navigation.
 *
 * Specs: 260px width, fixed left, dark background.
 * Active state: white bg, dark text, 600 weight.
 * Inactive: muted text, transparent bg.
 * Header: 52px height with logo and border-bottom.
 */
export function DSSidebar({
  logo,
  logoAlt = 'Logo',
  menuItems = [],
  onLogout,
  width = 220,
  children,
}) {
  const location = useLocation();

  const isActive = (path) =>
    location.pathname === path || location.pathname.startsWith(path + '/');

  return (
    <Box
      component="nav"
      sx={{
        width,
        minWidth: width,
        height: '100vh',
        position: 'fixed',
        top: 0,
        left: 0,
        borderRight: '1px solid #3d3d3a',
        backgroundColor: 'rgba(26, 26, 24, 0.95)',
        backdropFilter: 'blur(12px)',
        display: 'flex',
        flexDirection: 'column',
        zIndex: 50,
      }}
    >
      {/* Logo */}
      <Box
        component={Link}
        to={menuItems[0]?.path || '/'}
        sx={{
          display: 'flex',
          alignItems: 'center',
          textDecoration: 'none',
          px: 2.5,
          py: 2.5,
          borderBottom: '1px solid #3d3d3a',
        }}
      >
        {logo ? (
          <img src={logo} alt={logoAlt} style={{ height: '28px' }} />
        ) : (
          <Typography
            sx={{
              fontSize: '18px',
              fontWeight: 700,
              color: '#fafaf8',
              fontFamily: '"Geist", sans-serif',
            }}
          >
            {logoAlt}
          </Typography>
        )}
      </Box>

      {/* Nav Links */}
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5, px: 1.5, py: 2, flex: 1 }}>
        {menuItems.map((item) => (
          <Box
            key={item.text}
            component={Link}
            to={item.path}
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              px: 1.5,
              py: 1,
              borderRadius: '6px',
              fontSize: '14px',
              fontWeight: 500,
              fontFamily: '"Geist", sans-serif',
              textDecoration: 'none',
              transition: 'all 0.15s ease',
              ...(isActive(item.path)
                ? {
                    backgroundColor: '#fafaf8',
                    color: '#1a1a18',
                    fontWeight: 600,
                  }
                : {
                    color: '#a8a8a0',
                    '&:hover': {
                      color: '#fafaf8',
                      backgroundColor: 'rgba(255, 255, 255, 0.06)',
                    },
                  }),
            }}
          >
            {item.icon && (
              <Box
                component="span"
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  color: 'inherit',
                  '& svg': { fontSize: 18 },
                }}
              >
                {item.icon}
              </Box>
            )}
            {item.text}
          </Box>
        ))}
      </Box>

      {/* Custom bottom content */}
      {children}

      {/* Sign out */}
      {onLogout && (
        <Box sx={{ borderTop: '1px solid #3d3d3a', px: 1.5, py: 1.5 }}>
          <Button
            onClick={onLogout}
            fullWidth
            sx={{
              justifyContent: 'flex-start',
              fontSize: '14px',
              color: '#a8a8a0',
              '&:hover': {
                color: '#fafaf8',
                backgroundColor: 'rgba(255, 255, 255, 0.06)',
              },
              textTransform: 'none',
              fontWeight: 400,
              px: 1.5,
            }}
          >
            Sign out
          </Button>
        </Box>
      )}
    </Box>
  );
}

/**
 * Design System Navbar — landing page top navigation.
 *
 * Specs: 70px height, horizontal layout, logo + links left, CTA buttons right.
 */
export function DSNavbar({
  logo,
  logoText = 'Coached',
  links = [],
  onLogin,
  onSignup,
  sx = {},
}) {
  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        height: 70,
        padding: '0 48px',
        borderRadius: '8px',
        backgroundColor: '#1a1a18',
        borderBottom: '1px solid #3d3d3a',
        ...sx,
      }}
    >
      {/* Left: Logo + Links */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: '48px' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          {logo ? (
            <img src={logo} alt={logoText} style={{ height: '24px' }} />
          ) : (
            <>
              <Box
                sx={{
                  width: 28,
                  height: 28,
                  borderRadius: '6px',
                  backgroundColor: '#fafaf8',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <Typography sx={{ fontSize: '14px', fontWeight: 700, color: '#1a1a18' }}>
                  C
                </Typography>
              </Box>
              <Typography sx={{ fontSize: '16px', fontWeight: 700, color: '#fafaf8' }}>
                {logoText}
              </Typography>
            </>
          )}
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {links.map((link) => (
            <Box
              key={link.text}
              component={link.href ? 'a' : Link}
              to={!link.href ? link.path : undefined}
              href={link.href}
              sx={{
                padding: '10px 16px',
                borderRadius: '8px',
                fontSize: '14px',
                fontWeight: link.active ? 600 : 400,
                color: link.active ? '#fafaf8' : '#a8a8a0',
                backgroundColor: link.active ? '#2d2d2a' : 'transparent',
                textDecoration: 'none',
                fontFamily: '"Geist", sans-serif',
                '&:hover': {
                  color: '#fafaf8',
                  backgroundColor: 'rgba(255, 255, 255, 0.06)',
                },
              }}
            >
              {link.text}
            </Box>
          ))}
        </Box>
      </Box>

      {/* Right: Auth buttons */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        {onLogin && (
          <Button
            onClick={onLogin}
            sx={{
              color: '#a8a8a0',
              fontSize: '14px',
              textTransform: 'none',
              padding: '10px 16px',
              '&:hover': { color: '#fafaf8' },
            }}
          >
            Log in
          </Button>
        )}
        {onSignup && (
          <Button
            onClick={onSignup}
            sx={{
              backgroundColor: '#161616',
              color: '#fff',
              fontSize: '14px',
              textTransform: 'none',
              padding: '10px 20px',
              borderRadius: '8px',
              '&:hover': { backgroundColor: '#2a2a2a' },
            }}
          >
            Get Started
          </Button>
        )}
      </Box>
    </Box>
  );
}
