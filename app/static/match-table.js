// Shared by the homepage and Bot details; values are escaped before markup.
window.MatchTable = (() => {
    function escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
    }
    const escapeAttr = escapeHtml;
    const GLYPH = {
        bot: 'M9 10h.01M15 10h.01M8.5 15h7M12 3v2m-6 4H4m16 0h-2M6.75 7.5h10.5a2.25 2.25 0 0 1 2.25 2.25v6a2.25 2.25 0 0 1-2.25 2.25H6.75A2.25 2.25 0 0 1 4.5 15.75v-6A2.25 2.25 0 0 1 6.75 7.5Z',
        human: 'M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.501 20.118a7.5 7.5 0 0 1 14.997 0A17.733 17.733 0 0 0 12 19.5c-1.677 0-3.277.23-4.798.618Z',
        empty: 'M6 12h12'
    };
    function glyphSvg(kind, attrs) {
        return `<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.7" stroke="currentColor" aria-hidden="true"${attrs}><path stroke-linecap="round" stroke-linejoin="round" d="${GLYPH[kind]}"/></svg>`;
    }

    // Compact player name card used in the Latest Matches table.
    // Bots jump to /bot/<id>, people to /profile/<username>; both are links.
    // The winner's card carries a small green "W" corner badge.
    // The version renders in a smaller, lighter font than the bot name.
    function playerCard(name, isWinner, tone, botId, version, isHuman, rating) {
        if (!name) return '';
        const tones = {
            blue: 'bg-blue-100 text-blue-800 hover:bg-blue-200',
            purple: 'bg-purple-100 text-purple-800 hover:bg-purple-200'
        };
        // Bot ratings control their tone; humans keep their existing colors.
        const cls = isHuman ? (tones[tone] || tones.blue) : 'lm-bot-chip bot-rating-label';
        const hasRating = typeof rating === 'number' && Number.isFinite(rating);
        const ratingAttr = isHuman ? '' : ` data-bot-rating="${hasRating ? rating : ''}"`;
        const ratingTitle = !isHuman && hasRating ? ` · Current rating: ${rating.toFixed(2)}` : '';
        const glyph = glyphSvg(isHuman ? 'human' : 'bot', ' class="w-3.5 h-3.5 mr-1 opacity-80 flex-none"');
        const badge = isWinner
            ? '<span class="absolute -top-1.5 -right-1.5 flex items-center justify-center w-4 h-4 rounded-full bg-green-500 text-white text-[10px] font-bold shadow" title="Winner">W</span>'
            : '';
        const versionHtml = version ? `<span class="ml-1 text-xs font-normal opacity-70 flex-none">v${escapeHtml(version)}</span>` : '';
        // The name is the only unbounded part of the chip, so it gets its own box
        // for the ellipsis rule to act on; glyph and version never shrink.
        const inner = `${glyph}<span class="lm-pname">${escapeHtml(name)}</span>${versionHtml}${badge}`;
        // Old rows recorded the seat as the literal "HUMAN" and never stored who it
        // was, so there is no profile to open for those.
        const href = botId ? `/bot/${encodeURIComponent(botId)}`
            : (isHuman && name !== 'HUMAN' ? `/profile/${encodeURIComponent(name)}` : null);
        if (href) {
            const label = botId ? 'View bot' : 'View profile';
            return `<a href="${escapeAttr(href)}"${ratingAttr} class="lm-chip relative inline-flex items-center px-2.5 py-1 rounded-full ${cls} text-sm font-medium whitespace-nowrap transition-colors" title="${escapeAttr(label + ' — ' + name + ratingTitle)}">${inner}</a>`;
        }
        return `<span${ratingAttr} class="lm-chip relative inline-flex items-center px-2.5 py-1 rounded-full ${cls} text-sm font-medium whitespace-nowrap"${ratingTitle ? ` title="${escapeAttr('Current rating: ' + rating.toFixed(2))}"` : ''}>${inner}</span>`;
    }

    function ratingChange(delta) {
        if (typeof delta !== 'number' || !Number.isFinite(delta)) {
            return '<span class="lm-rating lm-rating-neutral" title="Rating change unavailable">-</span>';
        }
        const rounded = Number(delta.toFixed(2));
        const tone = rounded > 0 ? 'up' : rounded < 0 ? 'down' : 'neutral';
        const label = rounded > 0 ? '+' + rounded.toFixed(2) : rounded === 0 ? '0.00' : rounded.toFixed(2);
        return `<span class="lm-rating lm-rating-${tone}">${label}</span>`;
    }

    function render(tbody, matches, emptyMessage = 'No matches yet.', {showRatingDelta = false} = {}) {
        if (!tbody) return;
        tbody.innerHTML = '';
        if (!matches.length) {
            const row = tbody.insertRow();
            row.className = 'lm-empty';
            const cell = row.insertCell();
            cell.colSpan = 4;
            cell.textContent = emptyMessage;
            return;
        }
        matches.forEach(match => {
            // home.py already flattened match.player_1 / player_2 into
            // name strings plus player_1_id / player_1_version fields.
            const p1Card = playerCard(match.player_1, match.winner === 0, 'purple', match.player_1_id, match.player_1_version, match.player_1_is_human, match.player_1_rating);
            const p2Card = playerCard(match.player_2, match.winner === 1, 'purple', match.player_2_id, match.player_2_version, match.player_2_is_human, match.player_2_rating);
            const cards = [p1Card, p2Card].filter(Boolean);
            const playersStr = cards.length
                ? `<span class="lm-players">${cards.join('')}</span>`
                : '<span class="lm-dash">—</span>';

            const live = match.status === 'playing';
            let replayLink = '<span class="lm-dash">—</span>';
            if (match.status === 'finished' || live) {
                const label = live ? 'Watch live' : 'Watch replay';
                // No visible text, so the accessible name comes from aria-label.
                replayLink = `<a href="/match/${encodeURIComponent(match.id)}" class="lm-watch${live ? ' live' : ''}" title="${label}" aria-label="${label}">`
                    + (live
                        ? '<svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg><span class="lm-dot" aria-hidden="true"></span>'
                        : '<svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>')
                    + '</a>';
            }

            let date = fmtLocal(match.created_at);

            tbody.innerHTML += `
                <tr>
                    <td>${showRatingDelta ? ratingChange(match.rating_delta) : escapeHtml(match.game)}</td>
                    <td>${playersStr}</td>
                    <td>${replayLink}</td>
                    <td class="lm-time hidden sm:table-cell" title="${escapeHtml(match.created_at || '')}">${escapeHtml(date)}</td>
                </tr>
            `;
        });
        BotRating.apply(tbody);
    }
    return { render };
})();
