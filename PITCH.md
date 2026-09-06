# Product pitch

Most watchlists sort by percentage change, so the same volatile stocks top the list every
day. Smart Watchlist ranks by how *unusual* a move is for that stock: magnitude =
|return| / (σ√N), where σ is its own volatility over 750 one-minute samples and N the
trading minutes since you last signed in. The server stores baselines and σ; your browser
does the arithmetic, so serving cost barely grows with users. Prices are live from BSE on
a one-minute cadence, written only when the event time advances. Every failure reaches
the screen; nothing is simulated.
