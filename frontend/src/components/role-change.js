// The role in the "Edit person" dialog (SET-10).
// The dialog listed six roles, without Kid and Guest. For a kid the Role field was blank, and
// "Save changes" sent an empty role: the server failed and saved nothing, so a kid could not be
// edited at all (name, e-mail, limit, hours). Picking a role to fill the blank silently made
// the kid that role.

/**
 * What to send as the role when the dialog is saved: nothing, unless the person chose another one.
 * @param {string | undefined} chosen the value of the Role field
 * @param {string | undefined} current the person's role
 * @returns {{ role_id?: string }}
 */
export function roleChange(chosen, current) {
  if (!chosen || chosen === current) return {};
  return { role_id: chosen };
}

/**
 * Shows the person's role in the field. A role the list does not offer is added as it is, so
 * the field is never blank.
 * @param {HTMLSelectElement | null} select
 * @param {string} roleId
 * @param {string} [label]
 */
export function showRole(select, roleId, label) {
  if (!select || !roleId) return;
  if (![...select.options].some((o) => o.value === roleId)) {
    const option = document.createElement('option');
    option.value = roleId;
    option.textContent = label || roleId;
    select.append(option);
  }
  select.value = roleId;
}
