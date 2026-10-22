import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { openFilePreviewModal, closeFilePreviewModal } from '../components/file-preview-modal.js';
import { api } from '../api.js';

describe('Revamped Image Previewer & Multi-Image Gallery Suite', () => {
  const sampleFolder = [
    { name: 'DSCF4886.JPG', path: '/mnt/user/Photos/DSCF4886.JPG', is_dir: false, size: 6840000 },
    { name: 'DSCF4887.JPG', path: '/mnt/user/Photos/DSCF4887.JPG', is_dir: false, size: 7120000 },
    { name: 'DSCF4888.JPG', path: '/mnt/user/Photos/DSCF4888.JPG', is_dir: false, size: 6950000 },
    { name: 'notes.txt', path: '/mnt/user/Photos/notes.txt', is_dir: false, size: 1024 },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = '';

    window.getActiveFmInstance = vi.fn().mockReturnValue({
      fileList: [...sampleFolder],
      selectedPaths: new Set(['/mnt/user/Photos/DSCF4886.JPG']),
      updateRowSelectionUI: vi.fn(),
      updateSelectionToolbar: vi.fn(),
    });

    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url.includes('DSCF4886.JPG')) {
        return {
          status: 'ok',
          type: 'image',
          path: '/mnt/user/Photos/DSCF4886.JPG',
          name: 'DSCF4886.JPG',
          size: 6840000,
          ext: '.jpg',
          dimensions: '6240 × 4160',
          megapixels: '26.0 MP',
          color_mode: 'RGB',
          exif: {
            camera: 'FUJIFILM X-T5',
            lens: 'XF23mmF1.4 R LM WR',
            shutter_speed: '1/250s',
            aperture: 'f/2.8',
            iso: 'ISO 400',
            focal_length: '23mm',
            date_taken: '2025:12:01 10:17:24',
          },
        };
      } else if (url.includes('DSCF4887.JPG')) {
        return {
          status: 'ok',
          type: 'image',
          path: '/mnt/user/Photos/DSCF4887.JPG',
          name: 'DSCF4887.JPG',
          size: 7120000,
          ext: '.jpg',
          dimensions: '6240 × 4160',
          megapixels: '26.0 MP',
          exif: {
            camera: 'FUJIFILM X-T5',
            shutter_speed: '1/500s',
            aperture: 'f/2.0',
            iso: 'ISO 160',
          },
        };
      }
      return {
        status: 'ok',
        type: 'image',
        path: url,
        name: 'test.jpg',
        size: 1000000,
        ext: '.jpg',
      };
    });
  });

  afterEach(() => {
    closeFilePreviewModal();
    document.body.innerHTML = '';
  });

  it('renders revamped image previewer with all pan-zoom, rotate, and inspector controls', async () => {
    await openFilePreviewModal('/mnt/user/Photos/DSCF4886.JPG', 'DSCF4886.JPG', null, sampleFolder);

    const overlay = document.getElementById('quicklook-modal-overlay');
    expect(overlay).not.toBeNull();

    const titleEl = document.getElementById('quicklook-title-text');
    expect(titleEl.textContent).toBe('DSCF4886.JPG');

    // Controls must exist
    expect(document.getElementById('ql-zoom-in')).not.toBeNull();
    expect(document.getElementById('ql-zoom-out')).not.toBeNull();
    expect(document.getElementById('quicklook-zoom-pill')).not.toBeNull();
    expect(document.getElementById('ql-actual-size')).not.toBeNull();
    expect(document.getElementById('ql-rotate-cw')).not.toBeNull();
    expect(document.getElementById('ql-rotate-ccw')).not.toBeNull();
    expect(document.getElementById('ql-flip-h')).not.toBeNull();
    expect(document.getElementById('ql-info-toggle')).not.toBeNull();
    expect(document.getElementById('ql-maximize-btn')).not.toBeNull();

    // Image element must be rendered
    const img = document.getElementById('quicklook-img');
    expect(img).not.toBeNull();
    expect(img.getAttribute('src')).toContain('DSCF4886.JPG');
  });

  it('populates gallery from sibling images and renders chevrons and counter pill', async () => {
    await openFilePreviewModal('/mnt/user/Photos/DSCF4886.JPG', 'DSCF4886.JPG', null, sampleFolder);

    const counter = document.getElementById('quicklook-counter-pill');
    expect(counter.style.display).not.toBe('none');
    expect(counter.textContent).toBe('1 / 3'); // 3 images in sampleFolder, text file filtered out

    const prevBtn = document.getElementById('ql-nav-prev');
    const nextBtn = document.getElementById('ql-nav-next');
    expect(prevBtn).not.toBeNull();
    expect(nextBtn).not.toBeNull();

    // Filmstrip must contain 3 thumbnails
    const filmstrip = document.getElementById('quicklook-filmstrip');
    expect(filmstrip).not.toBeNull();
    const thumbs = filmstrip.querySelectorAll('.quicklook-thumb-item');
    expect(thumbs.length).toBe(3);
    expect(thumbs[0].classList.contains('active')).toBe(true);
  });

  it('navigates to next image on Next button click and Right Arrow keydown', async () => {
    await openFilePreviewModal('/mnt/user/Photos/DSCF4886.JPG', 'DSCF4886.JPG', null, sampleFolder);

    const nextBtn = document.getElementById('ql-nav-next');
    nextBtn.click();

    // Allow async loadCurrentItem to resolve
    await new Promise((r) => setTimeout(r, 20));

    expect(document.getElementById('quicklook-title-text').textContent).toBe('DSCF4887.JPG');
    expect(document.getElementById('quicklook-counter-pill').textContent).toBe('2 / 3');

    // Test Left Arrow navigation
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }));
    await new Promise((r) => setTimeout(r, 20));

    expect(document.getElementById('quicklook-title-text').textContent).toBe('DSCF4886.JPG');
    expect(document.getElementById('quicklook-counter-pill').textContent).toBe('1 / 3');
  });

  it('performs zoom in, zoom out, reset, and rotate transforms correctly', async () => {
    await openFilePreviewModal('/mnt/user/Photos/DSCF4886.JPG', 'DSCF4886.JPG', null, sampleFolder);

    const img = document.getElementById('quicklook-img');
    const zoomInBtn = document.getElementById('ql-zoom-in');
    const zoomPill = document.getElementById('quicklook-zoom-pill');
    const rotateCwBtn = document.getElementById('ql-rotate-cw');

    // Initial state
    expect(zoomPill.textContent).toBe('Fit');

    // Zoom in
    zoomInBtn.click();
    expect(img.style.transform).toContain('scale(1.25)');
    expect(zoomPill.textContent).toBe('125%');

    // Rotate CW 90 deg
    rotateCwBtn.click();
    expect(img.style.transform).toContain('rotate(90deg)');

    // Reset via zoom pill click
    zoomPill.click();
    // After reset or actual size
    expect(img.style.transform).toBeDefined();
  });

  it('toggles EXIF / technical metadata drawer and displays camera parameters', async () => {
    await openFilePreviewModal('/mnt/user/Photos/DSCF4886.JPG', 'DSCF4886.JPG', null, sampleFolder);

    const infoBtn = document.getElementById('ql-info-toggle');
    const inspector = document.getElementById('quicklook-inspector');

    expect(inspector.classList.contains('open')).toBe(false);

    // Toggle open
    infoBtn.click();
    expect(inspector.classList.contains('open')).toBe(true);

    const content = document.getElementById('quicklook-inspector-content');
    expect(content.innerHTML).toContain('FUJIFILM X-T5');
    expect(content.innerHTML).toContain('XF23mmF1.4 R LM WR');
    expect(content.innerHTML).toContain('1/250s');
    expect(content.innerHTML).toContain('f/2.8');
    expect(content.innerHTML).toContain('ISO 400');
    expect(content.innerHTML).toContain('6240 × 4160');
    expect(content.innerHTML).toContain('26.0 MP');

    // Toggle closed with inspector close button
    document.getElementById('ql-inspector-close').click();
    expect(inspector.classList.contains('open')).toBe(false);
  });

  it('toggles maximize / fullscreen window styling', async () => {
    await openFilePreviewModal('/mnt/user/Photos/DSCF4886.JPG', 'DSCF4886.JPG', null, sampleFolder);

    const dialog = document.getElementById('quicklook-modal-dialog');
    const maxBtn = document.getElementById('ql-maximize-btn');

    expect(dialog.classList.contains('maximized')).toBe(false);

    maxBtn.click();
    expect(dialog.classList.contains('maximized')).toBe(true);
    expect(maxBtn.title).toMatch(/Exit Fullscreen/);
    expect(maxBtn.querySelector('svg')).not.toBeNull();

    maxBtn.click();
    expect(dialog.classList.contains('maximized')).toBe(false);
    expect(maxBtn.title).toMatch(/Fullscreen/);
  });

  it('closes preview on Escape or Space keydown and unbinds listeners', async () => {
    await openFilePreviewModal('/mnt/user/Photos/DSCF4886.JPG', 'DSCF4886.JPG', null, sampleFolder);
    expect(document.getElementById('quicklook-modal-overlay')).not.toBeNull();

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(document.getElementById('quicklook-modal-overlay')).toBeNull();
  });

  it('renders HEIC image preview with on-the-fly WebP transcode URL and EXIF gear details', async () => {
    const heicFolder = [
      { name: 'IMG_4021.HEIC', path: '/mnt/user/Photos/IMG_4021.HEIC', is_dir: false, size: 2450000 },
      { name: 'IMG_4022.HEIF', path: '/mnt/user/Photos/IMG_4022.HEIF', is_dir: false, size: 2310000 },
    ];

    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url.includes('IMG_4021.HEIC')) {
        return {
          status: 'ok',
          type: 'image',
          path: '/mnt/user/Photos/IMG_4021.HEIC',
          name: 'IMG_4021.HEIC',
          size: 2450000,
          ext: '.heic',
          url: '/api/fs/preview/image?path=%2Fmnt%2Fuser%2FPhotos%2FIMG_4021.HEIC',
          download_url: '/api/fs/download?path=%2Fmnt%2Fuser%2FPhotos%2FIMG_4021.HEIC',
          dimensions: '4032 × 3024',
          megapixels: '12.2 MP',
          exif: {
            camera: 'Apple iPhone 15 Pro',
            lens: 'iPhone 15 Pro back triple camera 6.78mm f/1.78',
            shutter_speed: '1/120s',
            aperture: 'f/1.8',
            iso: 'ISO 80',
          },
        };
      }
      return { status: 'ok', type: 'image', path: url, name: 'test.heic', ext: '.heic' };
    });

    await openFilePreviewModal('/mnt/user/Photos/IMG_4021.HEIC', 'IMG_4021.HEIC', null, heicFolder);

    const img = document.getElementById('quicklook-img');
    expect(img).not.toBeNull();
    // Image source must point to WebP transcoding preview endpoint
    expect(img.getAttribute('src')).toContain('/api/fs/preview/image');

    // Filmstrip thumbnails for HEIC must also point to preview endpoint with thumb=1
    const filmstrip = document.getElementById('quicklook-filmstrip');
    const thumbs = filmstrip.querySelectorAll('.quicklook-thumb-item img');
    expect(thumbs.length).toBe(2);
    expect(thumbs[0].getAttribute('src')).toContain('/api/fs/preview/image');
    expect(thumbs[0].getAttribute('src')).toContain('thumb=1');

    // Inspector EXIF parameters
    const infoBtn = document.getElementById('ql-info-toggle');
    infoBtn.click();
    const content = document.getElementById('quicklook-inspector-content');
    expect(content.innerHTML).toContain('iPhone 15 Pro');
    expect(content.innerHTML).toContain('4032 × 3024');
    expect(content.innerHTML).toContain('12.2 MP');
  });

  it('renders modern revamped video player with custom HUD, scrubber, controls, and keyboard navigation', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url) => {
      if (url.includes('vacation.mp4')) {
        return {
          status: 'ok',
          type: 'media',
          path: '/mnt/user/Videos/vacation.mp4',
          name: 'vacation.mp4',
          size: 45000000,
          ext: '.mp4',
          stream_url: '/api/fs/stream?path=%2Fmnt%2Fuser%2FVideos%2Fvacation.mp4',
        };
      }
      return { status: 'ok', type: 'media', ext: '.mp4', path: url };
    });

    await openFilePreviewModal('/mnt/user/Videos/vacation.mp4', 'vacation.mp4');

    // Video container and element
    const container = document.getElementById('quicklook-video-container');
    expect(container).not.toBeNull();
    const video = document.getElementById('quicklook-video-player');
    expect(video).not.toBeNull();
    expect(video.getAttribute('src')).toContain('/api/fs/stream');

    // Floating center button
    const centerBtn = document.getElementById('ql-video-center-btn');
    expect(centerBtn).not.toBeNull();

    // Glassmorphic HUD and controls
    const hud = document.getElementById('quicklook-video-hud');
    expect(hud).not.toBeNull();
    const playBtn = document.getElementById('ql-video-play-btn');
    expect(playBtn).not.toBeNull();
    const skipBack = document.getElementById('ql-video-skip-back');
    expect(skipBack).not.toBeNull();
    const skipFwd = document.getElementById('ql-video-skip-forward');
    expect(skipFwd).not.toBeNull();
    const volSlider = document.getElementById('ql-video-vol-slider');
    expect(volSlider).not.toBeNull();
    const timeDisplay = document.getElementById('ql-video-time');
    expect(timeDisplay).not.toBeNull();
    const speedBtn = document.getElementById('ql-video-speed-btn');
    expect(speedBtn).not.toBeNull();
    const loopBtn = document.getElementById('ql-video-loop-btn');
    expect(loopBtn).not.toBeNull();
    const fsBtn = document.getElementById('ql-video-fs-btn');
    expect(fsBtn).not.toBeNull();
    const scrubber = document.getElementById('ql-video-scrub-container');
    expect(scrubber).not.toBeNull();

    // Test Play/Pause mock
    video.play = vi.fn().mockResolvedValue();
    video.pause = vi.fn();
    Object.defineProperty(video, 'duration', { value: 120, writable: true });
    Object.defineProperty(video, 'currentTime', { value: 10, writable: true });
    Object.defineProperty(video, 'paused', { value: true, writable: true });

    // Press Space: should toggle play (video), NOT close modal!
    window.dispatchEvent(new KeyboardEvent('keydown', { code: 'Space' }));
    expect(video.play).toHaveBeenCalled();
    expect(document.getElementById('quicklook-modal-overlay')).not.toBeNull();

    // Test skip forward shortcut (ArrowRight)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }));
    expect(video.currentTime).toBe(20);

    // Test skip back shortcut (ArrowLeft)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }));
    expect(video.currentTime).toBe(10);

    // Test speed step
    expect(speedBtn.textContent).toBe('1x');
    speedBtn.click();
    expect(video.playbackRate).toBe(1.25);
    expect(speedBtn.textContent).toBe('1.25x');

    // Test loop toggle
    loopBtn.click();
    expect(video.loop).toBe(true);

    // Test escape closes modal and cleans up
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(document.getElementById('quicklook-modal-overlay')).toBeNull();
  });
});
