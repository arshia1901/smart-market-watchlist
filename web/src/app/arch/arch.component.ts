import { CommonModule } from '@angular/common';
import { Component } from '@angular/core';

/**
 * The architecture document, as a route. Diagrams are inline SVG so the wiring is
 * exact and legible at any size; numbers come from the running system and the design
 * document, not from estimates.
 */
@Component({
  selector: 'app-arch',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './arch.component.html',
  styleUrl: './arch.component.css',
})
export class ArchComponent {
  readonly sections = [
    ['overview', '1. High-level architecture'],
    ['ingestion', '2.1 Ingestion tick'],
    ['statistics', '2.2 Statistics engine'],
    ['sessions', '2.3 Sessions and the shift register'],
    ['readpath', '2.4 Read path: shared vs personal'],
    ['warmup', '2.5 Warm-up on add'],
    ['failure', '2.6 Failure propagation'],
    ['scale', '3. Horizontal scaling on GCP'],
  ];
}
