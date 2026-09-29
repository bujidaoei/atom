export type V3GroupTodoStatus = 'pending' | 'in_progress' | 'completed' | 'cancelled';

export class V3GroupTodoNotFoundError extends Error {
  constructor() {
    super('todo not found');
    this.name = 'V3GroupTodoNotFoundError';
  }
}

export interface V3GroupTodo {
  todo_id: string;
  content: string;
  status: V3GroupTodoStatus;
  created_at: string;
  updated_at: string;
}

export type V3GroupTodoCommand =
  | { action: 'list'; all: boolean }
  | { action: 'add'; content: string }
  | { action: 'update'; todoId: string; content?: string; status?: V3GroupTodoStatus };
