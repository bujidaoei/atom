import { describe, expect, it } from 'vitest';

import {
  dueV3ScheduleOccurrence,
  mostRecentV3ScheduleOccurrence,
  nextV3ScheduleAt,
} from '../src/v3-automation-schedule.ts';

describe('V3 Automation schedule calculation', () => {
  it('projects the next visible occurrence with the same timezone rules used by dispatch', () => {
    expect(
      nextV3ScheduleAt(
        { id: 'daily', type: 'schedule', mode: 'recurring', cadence: 'daily', time: '09:00' },
        'Asia/Shanghai',
        new Date('2026-08-15T00:30:00.000Z'),
      ),
    ).toBe('2026-08-15T01:00:00.000Z');
  });
  it('uses the configured IANA timezone rather than the worker timezone', () => {
    const trigger = {
      id: 'daily',
      type: 'schedule' as const,
      mode: 'recurring' as const,
      cadence: 'daily' as const,
      time: '09:00',
    };
    expect(
      mostRecentV3ScheduleOccurrence(trigger, 'Asia/Shanghai', new Date('2026-08-15T01:00:30.000Z')),
    ).toEqual({
      scheduledAt: '2026-08-15T01:00:00.000Z',
      deliveryIdentity: 'schedule:daily:Asia/Shanghai:2026-08-15T09:00',
      latenessMs: 30_000,
    });
  });

  it('honors weekly weekdays and missed-run skip/run-once policy', () => {
    const trigger = {
      id: 'weekly',
      type: 'schedule' as const,
      mode: 'recurring' as const,
      cadence: 'weekly' as const,
      time: '09:00',
      daysOfWeek: [1],
    };
    const now = new Date('2026-08-19T04:00:00.000Z');
    expect(mostRecentV3ScheduleOccurrence(trigger, 'Asia/Shanghai', now)).toMatchObject({
      scheduledAt: '2026-08-17T01:00:00.000Z',
    });
    expect(dueV3ScheduleOccurrence(trigger, 'Asia/Shanghai', 'skip', now, 30_000)).toBeUndefined();
    expect(dueV3ScheduleOccurrence(trigger, 'Asia/Shanghai', 'run_once', now, 30_000)).toBeDefined();
  });

  it('never runs an occurrence scheduled before the active definition existed', () => {
    const trigger = {
      id: 'daily',
      type: 'schedule',
      mode: 'recurring',
      cadence: 'daily',
      time: '09:00',
    } as const;
    const now = new Date('2026-09-22T21:32:44.000Z');
    expect(dueV3ScheduleOccurrence(trigger, 'Asia/Shanghai', 'run_once', now, 30_000)).toBeDefined();
    expect(
      dueV3ScheduleOccurrence(trigger, 'Asia/Shanghai', 'run_once', now, 30_000, '2026-09-22T21:32:40.000Z'),
    ).toBeUndefined();
    expect(
      dueV3ScheduleOccurrence(trigger, 'Asia/Shanghai', 'run_once', now, 30_000, '2026-09-21T12:00:00.000Z'),
    ).toMatchObject({ scheduledAt: '2026-09-22T01:00:00.000Z' });
  });

  it('calculates the official hourly, monthly, and custom Cron repeat modes', () => {
    const now = new Date('2026-08-15T12:34:30.000Z');
    expect(
      nextV3ScheduleAt(
        { id: 'hourly', type: 'schedule', mode: 'recurring', cadence: 'hourly', time: '00:45' },
        'UTC',
        now,
      ),
    ).toBe('2026-08-15T12:45:00.000Z');
    expect(
      nextV3ScheduleAt(
        {
          id: 'monthly',
          type: 'schedule',
          mode: 'recurring',
          cadence: 'monthly',
          time: '09:15',
          dayOfMonth: 1,
        },
        'Asia/Shanghai',
        now,
      ),
    ).toBe('2026-09-01T01:15:00.000Z');
    expect(
      nextV3ScheduleAt(
        {
          id: 'custom',
          type: 'schedule',
          mode: 'recurring',
          cadence: 'custom',
          time: '00:00',
          cronExpression: '*/10 * * * *',
        },
        'UTC',
        now,
      ),
    ).toBe('2026-08-15T12:40:00.000Z');
  });

  it('does not release a one-time schedule before its absolute instant', () => {
    const trigger = {
      id: 'once',
      type: 'schedule' as const,
      mode: 'once' as const,
      runAt: '2026-08-15T09:00:00.000Z',
    };
    expect(
      mostRecentV3ScheduleOccurrence(trigger, 'Asia/Shanghai', new Date('2026-08-15T08:59:59.000Z')),
    ).toBeUndefined();
    expect(
      mostRecentV3ScheduleOccurrence(trigger, 'Asia/Shanghai', new Date('2026-08-15T09:00:00.000Z')),
    ).toMatchObject({ latenessMs: 0 });
  });
});
