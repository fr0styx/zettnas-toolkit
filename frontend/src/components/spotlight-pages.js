/**
 * Spotlight finds the Settings pages (SET-20, Overview 6a): "Search settings" in the sidebar opens
 * Spotlight, which knew apps and commands but no page. Each page is found by its name and by the
 * household's own words for it, in the person's language and in English. Loaded when Spotlight
 * first opens, so the first load carries none of it.
 */
import { t } from '../i18n.js';
import { openRoute } from '../router.js';

// [route, name key, name, words key, words (comma-separated)]
export const PAGES = [
  ['overview', 'mgmt.sidebar_overview', 'Overview', 'sp.kw_overview', 'status, home, summary, health, everything fine'],
  ['activity', 'mgmt.sidebar_activity', 'Activity', 'sp.kw_activity', 'history, events, log, what happened'],
  ['calendar', 'mgmt.sidebar_calendar', 'Calendar', 'sp.kw_calendar', 'dates, agenda, appointments'],
  ['storage', 'mgmt.sidebar_storage', 'Storage', 'sp.kw_storage', 'disks, drives, pools, space, full, raid, parity'],
  ['folders', 'mgmt.sidebar_shared_folders', 'Shared folders', 'sp.kw_folders', 'shares, network drive, folder, smb, samba, nfs, time machine'],
  ['backup', 'mgmt.sidebar_backup', 'Backup', 'sp.kw_backup', 'copy, restore, snapshot, cloud, safe, recovery'],
  ['people', 'mgmt.sidebar_people', 'People', 'sp.kw_people', 'users, family, kids, accounts, invite, guest'],
  ['away', 'mgmt.sidebar_away', 'Away from home', 'sp.kw_away', 'remote, outside, phone, tailscale, netbird, vpn, internet'],
  ['notifications', 'mgmt.sidebar_notifications', 'Notifications', 'sp.kw_notifications', 'alerts, email, push, telegram, messages'],
  ['kib', 'mgmt.sidebar_kib', 'Kib', 'sp.kw_kib', 'ai, assistant, ask, chat, search my files'],
  ['appearance', 'mgmt.sidebar_appearance', 'Appearance', 'sp.kw_appearance', 'theme, dark, light, wallpaper, colour, color, look, dock, widgets'],
  ['account', 'account.title', 'My account', 'sp.kw_account', 'my account, password, two-step, passkey, sign out, my data, devices'],
  ['security', 'mgmt.sidebar_security', 'Security', 'sp.kw_security', 'password, two-step, 2fa, sign-in, passkey, security check'],
  ['general', 'mgmt.sidebar_general', 'General', 'sp.kw_general', 'update, version, language, time, about, name'],
  ['network', 'mgmt.sidebar_network', 'Network', 'sp.kw_network', 'ip, address, ethernet, ports, wifi'],
  ['power', 'mgmt.sidebar_ups', 'Power', 'sp.kw_power', 'ups, battery, shutdown, power cut, outage'],
  ['hardware', 'mgmt.sidebar_hardware', 'Hardware', 'sp.kw_hardware', 'fans, temperature, cpu, front screen, lcd, light'],
  ['vms', 'mgmt.sidebar_vms', 'Virtual machines', 'sp.kw_vms', 'vm, windows, linux, virtual machine'],
];

// tabs inside a page: [the page whose rights it needs, pane, name key, name, words key, words]
export const TABS = [
  ['activity', 'mgmt-pane-events', 'mgmt.subtab_events', 'Event Log', 'sp.kw_t_events', 'log, audit, errors, warnings'],
  ['general', 'mgmt-pane-language', 'mgmt.subtab_language', 'Time, Language & Region', 'sp.kw_t_language', 'language, time zone, clock, date format, region'],
  ['hardware', 'mgmt-pane-hardware-fans', 'settings.tab_fans', 'Fans', 'sp.kw_t_fans', 'fan curve, noise, quiet, cooling, rpm'],
  ['hardware', 'mgmt-pane-hardware-led', 'settings.tab_led', 'LED Strip bar', 'sp.kw_t_led', 'led, light bar, colours'],
  ['storage', 'mgmt-pane-chassis-twin', 'mgmt.subtab_disks_chassis', 'Drives and bays', 'sp.kw_t_bays', 'bays, drive health, smart, failing disk, locate'],
  ['storage', 'mgmt-pane-storage-replication', 'mgmt.subtab_replication', 'Replication', 'sp.kw_t_replication', 'replicate, second nas, mirror'],
  ['storage', 'mgmt-pane-storage-remotes', 'mgmt.subtab_remotes', 'Remote & Cloud Storage', 'sp.kw_t_cloud', 'cloud, google drive, dropbox, s3, onedrive'],
  ['appearance', 'mgmt-pane-dock', 'mgmt.subtab_desktop', 'Desktop', 'sp.kw_t_desktop', 'dock, widgets, screen saver'],
  ['kib', 'mgmt-pane-ai-chat', 'ai.tab_chat', 'Ask Kib', 'sp.kw_t_ask', 'chat, question, ask'],
  ['network', 'mgmt-pane-network-services', 'mgmt.subtab_network_services', 'File Sharing Services', 'sp.kw_t_sharing', 'share links, public, funnel, apps from anywhere, family access'],
];

// everyday tasks (Overview 6b): [id, the page that holds it, its tab or '', task, words]
export const TASKS = [
  ['add_person', 'people', '', 'Add a person', 'invite, new user, family member, account'],
  ['child', 'people', '', 'Make an account for a child', 'kid, child, son, daughter, hours'],
  ['password', 'account', '', 'Change my password', 'password, sign-in, forgot'],
  ['two_step', 'account', '', 'Turn on two-step sign-in', '2fa, code, authenticator'],
  ['dark', 'appearance', '', 'Switch between dark and light', 'dark mode, light mode, night'],
  ['wallpaper', 'appearance', '', 'Change the wallpaper', 'background, picture'],
  ['time_zone', 'general', 'mgmt-pane-language', 'Set the time zone', 'clock, time'],
  ['language', 'general', 'mgmt-pane-language', 'Change the language', 'english, deutsch, français, español, 中文'],
  ['update', 'general', '', 'Update Kiboto', 'upgrade, new version'],
  ['power_cut', 'power', '', 'Get ready for a power cut', 'ups, battery, outage'],
  ['fans', 'hardware', 'mgmt-pane-hardware-fans', 'Make the fans quieter', 'fan noise, loud, quiet'],
  ['share', 'folders', '', 'Share a folder', 'new share, network folder'],
  ['backup', 'backup', '', 'Back up my files', 'copy, safe, external disk'],
  ['restore', 'backup', '', 'Get a file back', 'restore, deleted, yesterday'],
  ['phone', 'away', '', 'Open Kiboto on my phone away from home', 'remote, outside, travel'],
  ['alerts', 'notifications', '', 'Get alerts on my phone', 'push, telegram, email'],
  ['drives', 'storage', 'mgmt-pane-chassis-twin', "Check my drives' health", 'smart, failing, disk'],
  ['space', 'storage', '', 'See what uses the space', 'full, space, usage'],
];

/** "a, b , c" as ["a", "b", "c"], lower case. */
export function words(list) {
  return String(list || '')
    .toLowerCase()
    .split(',')
    .map((w) => w.trim())
    .filter(Boolean);
}

/** Spotlight entries for the pages, in the current language. */
export function pageItems() {
  return PAGES.map(([route, nameKey, name, wordsKey, english]) => ({
    id: `page-${route}`,
    title: t(nameKey, name),
    subtitle: t('sp.page_sub', 'Settings page'),
    icon: '⚙️',
    category: 'setting',
    route,
    keywords: [...new Set([...words(t(wordsKey, english)), ...words(english)])],
    run: () => openRoute(`#/${route}`),
  }));
}

/** Spotlight entries for tabs inside the pages; `route` carries the rights of their page. */
export function tabItems() {
  return TABS.map(([route, pane, nameKey, name, wordsKey, english]) => ({
    id: `tab-${pane}`,
    title: t(nameKey, name),
    subtitle: t('sp.tab_sub', 'Settings tab'),
    icon: '⚙️',
    category: 'setting',
    route,
    keywords: [...new Set([...words(t(wordsKey, english)), ...words(english)])],
    run: () => /** @type {any} */ (window).openManagementSection?.(pane),
  }));
}

/** Spotlight entries for everyday tasks; the line under each says which page it opens. */
export function taskItems() {
  const pageName = Object.fromEntries(PAGES.map(([route, nameKey, name]) => [route, t(nameKey, name)]));
  return TASKS.map(([id, route, pane, task, english]) => ({
    id: `task-${id}`,
    title: t(`sp.task_${id}`, task),
    subtitle: t('sp.task_sub', '{page} · Settings', { page: pageName[route] || route }),
    icon: '⚙️',
    category: 'setting',
    route,
    keywords: [...new Set([...words(t(`sp.kw_task_${id}`, english)), ...words(english)])],
    run: () => (pane ? /** @type {any} */ (window).openManagementSection?.(pane) : openRoute(`#/${route}`)),
  }));
}
