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

export interface LogStat {
  id: string;
  term: string;
  category: string;
  definition: string;
  source: "audio" | "selection";
  ts: number; // unix seconds
  learned: boolean;
}

export interface History {
  total_words: number;
  unique_words: number;
  total_jargon: number;
  words: WordStat[];
  terms: TermStat[];
  log: LogStat[];
}

export interface Config {
  enabled_categories: string[];
  notifier: string;
  cooldown_seconds: number;
  max_per_minute: number;
  notification_timeout: number;
  card_position: string;
  card_max: number;
  listen_system_audio: boolean;
  listen_microphone: boolean;
  listen_on_startup: boolean;
  vosk_model_path: string;
  hotkey_explain_selection: string;
  hotkey_mark_last_learned: string;
  hotkey_toggle_listening: string;
  close_to_tray: boolean;
  appearance: string;
  minimize_hint_shown: boolean;
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
}
