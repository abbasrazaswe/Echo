import type { Message } from "./api";

export interface StyleSettings {
  enabled: boolean;
  length: "brief" | "balanced" | "detailed";
  tone: "neutral" | "casual" | "warm" | "formal";
  punctuation: "standard" | "light" | "expressive";
  emoji_usage: "none" | "occasional";
  capitalization: "standard" | "mostly_lowercase";
  language:
    "match_user" | "english" | "urdu" | "roman_urdu" | "english_urdu_mix";
  preferred_words: string[];
}
export interface StyleRecord {
  revision: number;
  speaker: string | null;
  conversation_id: string | null;
  analysis_stale: boolean;
  settings: StyleSettings;
  suggested_settings: StyleSettings | null;
  analysis: {
    metrics: {
      message_count: number;
      mean_words: number;
      emoji_message_rate: number;
      terminal_punctuation_rate: number;
    };
    common_words: { word: string; occurrences: number }[];
    common_phrases: {
      phrase: string;
      message_count: number;
      source_message_ids: string[];
    }[];
    sample_limited: boolean;
    sample_truncated: boolean;
  } | null;
}
export interface Evaluation {
  revision: number;
  analysis_stale: boolean;
  checks: Record<string, boolean>;
  preferred_words_present: string[];
  not_evaluated: string[];
}
export type ArtifactKind = "summary" | "person" | "event" | "topic";
export type ArtifactStatus = "pending" | "confirmed" | "corrected" | "rejected";
export interface Artifact {
  id: string;
  conversation_id: string;
  kind: ArtifactKind;
  status: ArtifactStatus;
  content: string;
  generated_content: string;
  source_message_ids: string[];
  generated_source_message_ids: string[];
  method: string;
  uncertain: boolean;
  revision: number;
}
export interface ArtifactDetail extends Artifact {
  sources: Message[];
  generated_sources: Message[];
}
