import { CommonModule } from '@angular/common';
import {
  Component, ElementRef, HostListener, computed, effect, input, output, signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../api.service';
import { segments, step } from '../domain/match';

export interface Instrument { symbol: string; name: string; band_limit: string; }

/**
 * Typeahead over the instrument catalogue.
 *
 * A free-text box makes the user guess at exact symbols; a combobox lets them
 * recognise instead of recall. Everything here is presentation - the matching and
 * keyboard arithmetic live in domain/match.ts where they are unit tested.
 */
@Component({
  selector: 'app-stock-search',
  standalone: true,
  imports: [CommonModule, FormsModule],
  styleUrl: './stock-search.component.css',
  templateUrl: './stock-search.component.html',
})
export class StockSearchComponent {
  /** Symbols already on the watchlist - shown, but not offered again. */
  readonly existing = input<string[]>([]);
  readonly picked = output<string>();

  readonly query = signal('');
  readonly options = signal<Instrument[]>([]);
  readonly highlighted = signal(-1);
  readonly open = signal(false);
  readonly busy = signal(false);

  private debounce?: number;

  readonly held = computed(() => new Set(this.existing()));

  constructor(private api: ApiService, private host: ElementRef<HTMLElement>) {
    // An empty box offers the whole catalogue rather than nothing: browsing is a
    // legitimate way to use a list of twelve.
    effect(() => { if (this.open() && !this.query()) void this.fetch(''); });
  }

  parts(text: string) { return segments(text, this.query()); }

  onInput(value: string): void {
    this.query.set(value);
    this.open.set(true);
    clearTimeout(this.debounce);
    // One request per pause, not one per keystroke.
    this.debounce = setTimeout(() => void this.fetch(value), 140) as unknown as number;
  }

  private async fetch(q: string): Promise<void> {
    this.busy.set(true);
    try {
      this.options.set(await this.api.search(q));
      this.highlighted.set(this.options().length ? 0 : -1);
    } finally {
      this.busy.set(false);
    }
  }

  onKey(event: KeyboardEvent): void {
    const n = this.options().length;
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault();
        this.open.set(true);
        this.highlighted.set(step(this.highlighted(), 1, n));
        break;
      case 'ArrowUp':
        event.preventDefault();
        this.highlighted.set(step(this.highlighted(), -1, n));
        break;
      case 'Enter': {
        const choice = this.options()[this.highlighted()];
        if (choice) { event.preventDefault(); this.choose(choice); }
        break;
      }
      case 'Escape':
        this.close();
        break;
    }
  }

  choose(option: Instrument): void {
    if (this.held().has(option.symbol)) return;
    this.picked.emit(option.symbol);
    this.query.set('');
    this.close();
  }

  close(): void { this.open.set(false); this.highlighted.set(-1); }

  focus(): void { this.open.set(true); }

  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent): void {
    if (!this.host.nativeElement.contains(event.target as Node)) this.close();
  }
}
