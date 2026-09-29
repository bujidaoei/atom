export type V3GoalPauseReason =
  'user_stop' | 'awaiting_user' | 'turn_limit' | 'no_progress' | 'execution_error' | 'leader_unavailable';

export interface V3ConversationGoalState {
  goal: {
    id: string;
    status: 'active' | 'paused' | 'completed';
    content: string;
    generation: number;
    revision: number;
    turnLimit: number;
    createdAt: string;
    updatedAt: string;
    createdBy: string;
    updatedBy: string;
    requestedBy: string;
    sourceMessageId: string;
    lastHumanMessageId: string;
    lastHumanMessageSequence: number;
    resultMessageId: string | null;
    pauseReason: V3GoalPauseReason | null;
  };
  runtime: { turnCount: number; lastBusinessMessageSequence: number };
}

export interface V3GoalVersion {
  goalId: string;
  generation: number;
  revision: number;
}

export type V3GoalMutation =
  | { action: 'create'; content: string; turnLimit: number }
  | (V3GoalVersion & { action: 'update' | 'reopen'; content: string; turnLimit: number })
  | (V3GoalVersion & { action: 'pause'; reason: V3GoalPauseReason })
  | (V3GoalVersion & { action: 'complete'; resultMessageId: string });
