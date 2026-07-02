import { invoke } from "@tauri-apps/api/core";
import type {
  AudioStatus,
  Config,
  Detail,
  Entry,
  History,
  Knowledge,
} from "./types";

export const getEntries = () => invoke<Entry[]>("get_entries");
export const getKnowledge = () => invoke<Knowledge>("get_knowledge");
export const getHistory = () => invoke<History>("get_history");
export const getFillerWords = () => invoke<string[]>("get_filler_words");
export const clearHistory = () => invoke("clear_history");
export const getLibraryDetail = (id: string) =>
  invoke<Detail | null>("get_library_detail", { id });

export const getConfig = () => invoke<Config>("get_config");
export const setConfigKey = (key: string, value: unknown) =>
  invoke("set_config_key", { key, value });
export const beginCardPlacement = () => invoke("begin_card_placement");
export const saveCardPlacement = () =>
  invoke<{ x: number; y: number }>("save_card_placement");

export const markLearned = (id: string) => invoke("mark_learned", { id });
export const unlearn = (id: string) => invoke("unlearn", { id });
export const resetProgress = () => invoke("reset_progress");
export const exportProgress = (path: string) =>
  invoke("export_progress", { path });

export const explainSelection = () => invoke("explain_selection");
export const markLastLearned = () => invoke("mark_last_learned");
export const openUrl = (url: string) => invoke("open_url", { url });
export const focusLibraryTerm = (id: string) =>
  invoke("focus_library_term", { id });
export const quitApp = () => invoke("quit_app");

export const startupEnabled = () => invoke<boolean>("startup_enabled");
export const setStartup = (enabled: boolean) =>
  invoke("set_startup", { enabled });

export const audioStatus = () => invoke<AudioStatus>("audio_status");
export const isListening = () => invoke<boolean>("is_listening");
export const toggleListening = () => invoke<boolean>("toggle_listening");

const CATEGORY_COLORS: Record<string, string> = {
  tech: "var(--cyan)",
  business: "var(--orange)",
  companies: "var(--teal)",
  general: "var(--purple)",
  filler: "var(--gold)",
};

export function categoryColor(category: string): string {
  return CATEGORY_COLORS[category] ?? "var(--accent)";
}
