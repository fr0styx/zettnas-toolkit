// Every language at once, for tests and the translation lint. The app loads them one at a time.
import de from './de.js';
import en from './en.js';
import es from './es.js';
import fr from './fr.js';
import zh from './zh.js';

export const ALL_TRANSLATIONS = { en, de, zh, fr, es };
