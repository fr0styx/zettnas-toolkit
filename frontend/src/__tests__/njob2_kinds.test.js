import { describe, it, expect } from 'vitest';
import { jobRowHtml } from '../components/jobs-centre.js';
import { ALL_TRANSLATIONS as all } from '../locales/all.js';

// NJOB-2: the new kinds of background work have a name in the Jobs centre in every language
const KINDS = ['docker_cleanup', 'model_download', 'app_install', 'vm_download', 'smart_test', 'storage_check', 'mover',
  'replication', 'photo_captions', 'photo_vectors', 'restore', 'rollback', 'convert'];
const TITLES = ['docker_cleanup', 'model', 'app_install', 'iso', 'smart_test', 'parity', 'mover', 'scrub', 'replication',
  'captions', 'photo_vectors'];

describe('more background work in the Jobs centre (NJOB-2)', () => {
  it('names each kind instead of showing its key', () => {
    const html = jobRowHtml({ id: 'smart:sdb', kind: 'smart_test', status: 'running', percent: 30, title: 'x',
      title_id: 'jobs.t.smart_test', title_params: { test: 'long', disk: 'WDC (sdb)' } }, true);
    expect(html).toContain('Drive test');
    expect(html).toContain('SMART long test on WDC (sdb)');
    expect(jobRowHtml({ id: 'storage:mover', kind: 'mover', status: 'paused', title: 'x', title_id: 'jobs.t.mover' }, true))
      .toContain('Moving files between the cache and the array');
  });

  it('has every kind and title in all five languages', () => {
    for (const [lang, strings] of Object.entries(all)) {
      for (const k of KINDS) expect(strings[`jobs.kind_${k}`], `${lang} jobs.kind_${k}`).toBeTruthy();
      for (const k of TITLES) expect(strings[`jobs.t.${k}`], `${lang} jobs.t.${k}`).toBeTruthy();
    }
  });
});
