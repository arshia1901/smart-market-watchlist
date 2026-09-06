import { Component } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

/** The shell: one nav, one outlet. The watchlist and the architecture document are routes. */
@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  template: `
    <nav class="nav">
      <div class="nav-inner">
        <a class="brand" routerLink="/">
          <span class="brand-name">Smart Watchlist</span>
          <span class="brand-sub">ranked by how <em>unusual</em> a move is, not how big</span>
        </a>
        <div class="links">
          <a routerLink="/" routerLinkActive="active" [routerLinkActiveOptions]="{ exact: true }">Watchlist</a>
          <a routerLink="/arch" routerLinkActive="active" class="arch-btn">Architecture</a>
        </div>
      </div>
    </nav>
    <router-outlet />
  `,
  styles: [`
    .nav { border-bottom: 1px solid #e5e7eb; background: #fff; position: sticky; top: 0; z-index: 30; }
    .nav-inner { max-width: 1080px; margin: 0 auto; padding: 12px 20px; display: flex; align-items: center;
                 justify-content: space-between; gap: 16px; font: 14px ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif; }
    .brand { text-decoration: none; color: #16181d; display: flex; flex-direction: column; }
    .brand-name { font-weight: 700; font-size: 17px; letter-spacing: -0.01em; }
    .brand-sub { font-size: 12px; color: #6b7280; } .brand-sub em { font-style: normal; font-weight: 600; color: #16181d; }
    .links { display: flex; gap: 8px; }
    .links a { text-decoration: none; color: #374151; padding: 7px 12px; border-radius: 7px; font-weight: 500; }
    .links a:hover { background: #f3f4f6; }
    .links a.active { background: #111827; color: #fff; }
    .arch-btn { border: 1px solid #d1d5db; }
  `],
})
export class AppComponent {}
