import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit, computed, signal } from '@angular/core';
import { ApiService } from '../api.service';

interface Beat {
  last_run: number; duration_ms: number; interval_seconds?: number; next_run?: number;
  tracked?: number; applied?: number; applied_total?: number; dropped_late?: number;
  unchanged?: number; provider?: string; consumed?: number; windows?: number; rated?: number;
}
interface Status { now: number; grid_seconds: number; provider: string; cache: string; services: Record<string, Beat>; }

/**
 * What the scheduled pipeline is doing. A batch system that reports nothing looks
 * exactly like a stalled one; this strip is how a viewer tells them apart.
 *
 * And when the STATUS ENDPOINT itself is unreachable, the strip says that - it does
 * not keep repeating a stale "cache up" and then blame the engines for going quiet.
 */
@Component({
  selector: 'app-batch-status',
  standalone: true,
  imports: [CommonModule],
  styleUrl: './batch-status.component.css',
  templateUrl: './batch-status.component.html',
})
export class BatchStatusComponent implements OnInit, OnDestroy {
  readonly status = signal<Status | null>(null);
  readonly unreachableSince = signal<number | null>(null);
  readonly tick = signal(0);
  private timers: number[] = [];

  constructor(private api: ApiService) {}

  ngOnInit(): void {
    void this.poll();
    this.timers.push(setInterval(() => this.poll(), 5000) as unknown as number);
    this.timers.push(setInterval(() => this.tick.update((t) => t + 1), 1000) as unknown as number);
  }
  ngOnDestroy(): void { this.timers.forEach(clearInterval); }

  private async poll(): Promise<void> {
    try {
      this.status.set(await this.api.status() as Status);
      this.unreachableSince.set(null);
    } catch {
      if (this.unreachableSince() === null) this.unreachableSince.set(Date.now());
    }
  }

  /** How long the status endpoint has been down - ticking. */
  unreachableFor(): number {
    this.tick();
    const t = this.unreachableSince(); return t ? Math.round((Date.now() - t) / 1000) : 0;
  }

  readonly cadence = computed(() => {
    const s = this.status();
    const secs = s?.services['ingestion']?.interval_seconds ?? s?.grid_seconds;
    if (!secs) return 'cadence unknown';
    return secs >= 60 ? `batch every ${Math.round(secs / 60)} min` : `batch every ${Math.round(secs)}s`;
  });

  age(beat: Beat): number { this.tick(); return Math.max(0, Math.round(Date.now() / 1000 - beat.last_run)); }

  /** Late by more than two cadences is wrong, not idle. */
  stalled(beat: Beat, name: string): boolean {
    const budget = name === 'ingestion' ? (beat.interval_seconds ?? 60) * 2 + 15 : 30;
    return this.age(beat) > budget;
  }

  countdown(beat: Beat): string {
    this.tick();
    const left = Math.round((beat.next_run ?? 0) - Date.now() / 1000);
    return left > 0 ? `next in ${left}s` : 'due now';
  }
}
