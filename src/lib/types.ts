export interface Entry {
  id: string;
  term: string;
  definition: string;
  category: string;
  aliases: string[];
  strict: boolean;
}

export interface Detail {
  extended: string;
  source: string | null;
  url: string | null;
}

export interface Knowledge {
  learned: string[];
  count: number;
}

export interface WordStat {
  word: string;
  count: number;
}

export interface TermStat {
  id: string;
  term: string;
  category: string;
  definition: string;
  learned: boolean;
  count: number;
}

/** One calendar day's microphone totals (aggregates only, no content). */
export interface DayStat {
  date: string; // "YYYY-MM-DD" (local)
  mic_words: number;
  mic_filler: number;
}

export interface History {
  total_words: number;
  unique_words: number;
  total_jargon: number;
  words: WordStat[];
  terms: TermStat[];
  /** Microphone-only filler tracking (the filler-reduction goals). */
  mic_words: number;
  mic_filler: number;
  mic_fillers: WordStat[];
  days: DayStat[];
}

export interface Config {
  enabled_categories: string[];
  notifier: string;
  cooldown_seconds: number;
  max_per_minute: number;
  notification_timeout: number;
  card_position: string;
  card_custom_x: number;
  card_custom_y: number;
  card_max: number;
  listen_system_audio: boolean;
  listen_microphone: boolean;
  listen_on_startup: boolean;
  /** Global hotkeys; an empty string means unbound (action inactive). */
  hotkey_explain_selection: string;
  hotkey_mark_last_learned: string;
  hotkey_toggle_listening: string;
  hotkey_dictate: string;
  /** How hotkey dictation ends: "toggle" (second press) | "hold" (release). */
  dictate_mode: string;
  close_to_tray: boolean;
  appearance: string;
  minimize_hint_shown: boolean;
  track_history: boolean;
  /** Filler-reduction goal: max % of mic words that may be filler; 0 = off. */
  filler_goal_percent: number;
}

export interface AudioStatus {
  listening: boolean;
  ready: boolean;
  reason: string;
  model: string;
}

export interface CardPayload {
  entry: Entry;
  timeout: number;
  maxCards: number;
  position: string;
  customX: number;
  customY: number;
}
