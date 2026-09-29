import { CronExpressionParser } from 'cron-parser';

import type { V3AutomationTrigger } from '../../product-contracts/src/v3.ts';

export interface V3ScheduleOccurrence {
  scheduledAt: string;
  deliveryIdentity: string;
  latenessMs: number;
}

interface LocalParts {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  weekday: number;
}

const weekdays = new Map([
  ['Sun', 0],
  ['Mon', 1],
  ['Tue', 2],
  ['Wed', 3],
  ['Thu', 4],
  ['Fri', 5],
  ['Sat', 6],
]);

function localParts(date: Date, timezone: string): LocalParts {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
    weekday: 'short',
  }).formatToParts(date);
  const values = new Map(parts.map(({ type, value }) => [type, value]));
  const weekday = weekdays.get(values.get('weekday') ?? '');
  if (weekday === undefined) throw new Error('Unable to resolve Automation schedule weekday');
  return {
    year: Number(values.get('year')),
    month: Number(values.get('month')),
    day: Number(values.get('day')),
    hour: Number(values.get('hour')),
    minute: Number(values.get('minute')),
    weekday,
  };
}

function dateLabel(parts: Omit<LocalParts, 'weekday'>): string {
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${parts.year}-${pad(parts.month)}-${pad(parts.day)}T${pad(parts.hour)}:${pad(parts.minute)}`;
}

function recurringCron(
  trigger: Extract<V3AutomationTrigger, { type: 'schedule'; mode: 'recurring' }>,
): string {
  const [hour, minute] = trigger.time.split(':').map(Number) as [number, number];
  if (trigger.cadence === 'hourly') return `${minute} * * * *`;
  if (trigger.cadence === 'daily') return `${minute} ${hour} * * *`;
  if (trigger.cadence === 'weekdays') return `${minute} ${hour} * * 1-5`;
  if (trigger.cadence === 'weekly') {
    return `${minute} ${hour} * * ${(trigger.daysOfWeek ?? [1]).join(',')}`;
  }
  if (trigger.cadence === 'monthly') return `${minute} ${hour} ${trigger.dayOfMonth ?? 1} * *`;
  return trigger.cronExpression ?? '0 * * * *';
}

export function mostRecentV3ScheduleOccurrence(
  trigger: Extract<V3AutomationTrigger, { type: 'schedule' }>,
  timezone: string,
  now: Date,
): V3ScheduleOccurrence | undefined {
  if (trigger.mode === 'once') {
    const scheduled = new Date(trigger.runAt);
    const latenessMs = now.getTime() - scheduled.getTime();
    return latenessMs < 0
      ? undefined
      : {
          scheduledAt: scheduled.toISOString(),
          deliveryIdentity: `schedule:${trigger.id}:${scheduled.toISOString()}`,
          latenessMs,
        };
  }
  const scheduled = CronExpressionParser.parse(recurringCron(trigger), {
    currentDate: new Date(now.getTime() + 1),
    tz: timezone,
  })
    .prev()
    .toDate();
  const local = localParts(scheduled, timezone);
  return {
    scheduledAt: scheduled.toISOString(),
    deliveryIdentity: `schedule:${trigger.id}:${timezone}:${dateLabel(local)}`,
    latenessMs: now.getTime() - scheduled.getTime(),
  };
}

export function nextV3ScheduleAt(
  trigger: Extract<V3AutomationTrigger, { type: 'schedule' }>,
  timezone: string,
  now: Date,
): string | undefined {
  if (trigger.mode === 'once') {
    const scheduled = new Date(trigger.runAt);
    return scheduled.getTime() > now.getTime() ? scheduled.toISOString() : undefined;
  }
  return CronExpressionParser.parse(recurringCron(trigger), {
    currentDate: now,
    tz: timezone,
  })
    .next()
    .toDate()
    .toISOString();
}

export function dueV3ScheduleOccurrence(
  trigger: Extract<V3AutomationTrigger, { type: 'schedule' }>,
  timezone: string,
  missedRunPolicy: 'skip' | 'run_once',
  now: Date,
  pollingIntervalMs: number,
  /** Recurring slots scheduled before this instant (the active definition's creation) never run. */
  notBefore?: string,
): V3ScheduleOccurrence | undefined {
  const occurrence = mostRecentV3ScheduleOccurrence(trigger, timezone, now);
  if (!occurrence) return undefined;
  if (
    trigger.mode === 'recurring' &&
    notBefore &&
    Date.parse(occurrence.scheduledAt) < Date.parse(notBefore)
  ) {
    return undefined;
  }
  const graceMs = Math.max(90_000, pollingIntervalMs * 2);
  return missedRunPolicy === 'skip' && occurrence.latenessMs > graceMs ? undefined : occurrence;
}
