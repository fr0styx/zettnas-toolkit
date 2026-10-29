/**
 * The names of the roles, in the person's language: the one map every screen uses (UX-24).
 * Only translations here, so anything can import it.
 */
import { t } from '../i18n.js';

// The one place roles get their names, in the person's language (UX-24)
const ROLE_NAMES = {
  superadmin: () => t('role.superadmin', 'Administrator'),
  storage_admin: () => t('role.storage_admin', 'Storage admin'),
  app_operator: () => t('role.app_operator', 'App manager'),
  backup_operator: () => t('role.backup_operator', 'Backup manager'),
  share_user: () => t('role.share_user', 'Family member'),
  auditor: () => t('role.auditor', 'Viewer'),
};

export const ROLE_IDS = Object.keys(ROLE_NAMES);

/** A role's name for people; a custom role keeps the name it was given. */
export function formatRole(roleId, fallback = '') {
  const fn = ROLE_NAMES[roleId];
  return fn ? fn() : fallback || roleId;
}
