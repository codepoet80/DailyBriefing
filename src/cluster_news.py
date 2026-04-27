import difflib
import re
import unicodedata


STOP_WORDS = {
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
    'should', 'may', 'might', 'must', 'shall', 'can', 'its', 'it',
    'and', 'but', 'or', 'nor', 'to', 'of', 'in', 'for', 'on', 'with',
    'at', 'by', 'from', 'up', 'about', 'into', 'says', 'say', 'said',
    'after', 'over', 'also', 'just', 'new', 'more', 'than', 'his', 'her',
    'their', 'our', 'your', 'my', 'who', 'what', 'how', 'why', 'when',
    'this', 'that', 'these', 'those', 'not', 'no', 'as', 'if', 'so'
}


def normalize_title(title):
    title = unicodedata.normalize('NFKD', title.lower())
    title = re.sub(r'[^\w\s]', ' ', title)
    words = [w for w in title.split() if w not in STOP_WORDS and len(w) > 2]
    return ' '.join(words)


def title_similarity(a, b):
    na = normalize_title(a)
    nb = normalize_title(b)
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def cluster_stories(stories, threshold=0.65, importance_threshold=2):
    """
    Groups similar cross-source stories. Returns (important, regular).
    Modular: swap this file for a smarter implementation without touching anything else.
    """
    clusters = []
    used = set()

    for i, story in enumerate(stories):
        if i in used:
            continue
        cluster = [story]
        used.add(i)

        for j, other in enumerate(stories):
            if j in used or j == i:
                continue
            if other['source'] == story['source']:
                continue
            if title_similarity(story['title'], other['title']) >= threshold:
                cluster.append(other)
                used.add(j)

        clusters.append(cluster)

    important = []
    regular = []

    for cluster in clusters:
        source_names = list({s['source'] for s in cluster})
        is_important = _is_important(cluster, source_names, importance_threshold)

        if is_important:
            # Prefer a non-tech source as the canonical story for summary
            candidates = [s for s in cluster if not s.get('source_tech')]
            best = candidates[0] if candidates else cluster[0]

            important.append({
                'title': best['title'],
                'url': best['url'],
                'summary': best.get('summary', ''),
                'sources': source_names,
                'source_count': len(source_names),
            })
        else:
            s = cluster[0]
            regular.append({
                'title': s['title'],
                'url': s['url'],
                'summary': s.get('summary', ''),
                'source': s['source'],
            })

    important.sort(key=lambda x: x['source_count'], reverse=True)

    return important, regular


def _is_important(cluster, source_names, importance_threshold):
    if any(s.get('always_important') for s in cluster):
        return True

    # Verge + Wired both present
    vw_sources = {s['source'] for s in cluster if s.get('verge_wired_pair')}
    if len(vw_sources) >= 2:
        return True

    if len(source_names) >= importance_threshold:
        return True

    return False
