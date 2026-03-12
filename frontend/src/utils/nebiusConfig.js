/**
 * Nebius AI Cloud Provider Configuration
 * 
 * This configuration object is used in ManageInstances.js to define
 * the Nebius provider settings, required fields, and help text.
 */

export const NEBius_PROVIDER_CONFIG = {
  id: 'nebius',
  label: 'Nebius',
  logo: 'https://nebius.com/favicon.ico',
  name: 'Nebius AI Cloud',
  color: '#0b7c7e',
  bgColor: '#1a1a18',
  requiredFields: ['Service Account JSON', 'Project ID'],
  helpUrl: 'https://docs.nebius.com/compute/virtual-machines/creating/regular-vm',
  helpText: 'To get your Nebius credentials:\n1. In Nebius Console, go to Administration → IAM → Service accounts\n2. Create or select a service account and copy the Service Account ID\n3. Create an authorized key (RSA) and copy its ID\n4. Download the private key PEM file\n5. Paste the entire JSON credentials object below (or individual fields)\n6. Provide your Project ID that maps to your region',
};

/**
 * Helper function to parse Nebius credentials from various formats
 * 
 * @param {string|object} credentials - Can be:
 *   - JSON string with full credentials object
 *   - Object with service_account_id, key_id, private_key, project_id
 *   - Object with nested structure
 * 
 * @returns {object} Normalized credentials object
 */
export function parseNebiusCredentials(credentials) {
  if (!credentials) {
    return null;
  }

  // If it's already an object, use it
  if (typeof credentials === 'object' && !Array.isArray(credentials)) {
    // Check if it's a service account JSON (has service_account_id at root)
    if (credentials.service_account_id) {
      return {
        service_account_id: credentials.service_account_id,
        key_id: credentials.key_id || credentials.authorized_key_id,
        private_key: credentials.private_key || credentials.privateKey,
        project_id: credentials.project_id || credentials.projectId,
      };
    }
    
    // If it has nested structure, extract
    if (credentials.credentials) {
      return parseNebiusCredentials(credentials.credentials);
    }
    
    return credentials;
  }

  // If it's a string, try to parse as JSON
  if (typeof credentials === 'string') {
    try {
      const parsed = JSON.parse(credentials);
      return parseNebiusCredentials(parsed);
    } catch (e) {
      // If not JSON, might be just the private key
      return {
        private_key: credentials,
      };
    }
  }

  return null;
}

/**
 * Validate Nebius credentials structure
 * 
 * @param {object} credentials - Credentials object to validate
 * @returns {boolean} True if valid
 */
export function validateNebiusCredentials(credentials) {
  if (!credentials) return false;
  
  const parsed = parseNebiusCredentials(credentials);
  if (!parsed) return false;
  
  return !!(
    parsed.service_account_id &&
    parsed.key_id &&
    parsed.private_key
  );
}

