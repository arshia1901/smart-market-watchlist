import { Routes } from '@angular/router';
import { WatchlistPageComponent } from './watchlist/watchlist-page.component';
import { ArchComponent } from './arch/arch.component';

export const routes: Routes = [
  { path: '', component: WatchlistPageComponent, pathMatch: 'full' },
  { path: 'arch', component: ArchComponent },
  { path: '**', redirectTo: '' },
];
