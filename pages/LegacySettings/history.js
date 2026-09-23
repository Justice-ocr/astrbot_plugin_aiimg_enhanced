export function createHistoryController({ $, bridge, showToast }) {
  let page = 1, pages = 1, generation = 0, selected = null, detailVersion = 0;
  let loaded = false;
  const modes = { text: '文生图', draw: '文生图', edit: '改图', selfie_ref: '自拍' };
  const date = value => new Date(value * 1000).toLocaleString();
  const previews = new Map();

  async function image(id, original = false) {
    const result = await bridge.apiGet('get_history_image', { id, original: original ? '1' : '0' });
    if (!result.success || !/^data:image\/(png|jpeg|webp|gif);base64,/.test(result.image_data || '')) {
      throw new Error(result.error || '图片读取失败');
    }
    return result;
  }

  async function openDetail(item) {
    selected = item;
    const version = ++detailVersion;
    $('history-detail-title').textContent = `图片 ${item.sequence} · 记录 ID ${item.id}`;
    $('history-detail-meta').textContent = [
      date(item.created_at), modes[item.mode] || '图片',
      item.provider, item.output,
      item.parent_image_id ? `源图 #${item.parent_image_id}` : '',
    ].filter(Boolean).join(' · ');
    $('history-detail-session').textContent = [
      `消息来源：${item.origin || '未记录'}`,
      `会话：${item.conversation_title || item.conversation || '默认会话'}`,
      item.conversation_title ? `会话 ID：${item.conversation}` : '',
      `用户：${item.sender || '未记录'}`,
      `机器人：${item.bot || '未记录'}`,
    ].filter(Boolean).join('\n');
    $('history-detail-prompt').textContent = item.prompt || '未记录';
    $('history-detail-effective').textContent = item.effective_prompt || item.prompt || '未记录';
    $('history-detail-image').removeAttribute('src');
    $('history-detail-image').hidden = true;
    $('history-download').disabled = !item.available;
    $('history-detail-status').textContent = item.available ? '正在加载预览…' : '图片缓存已过期';
    $('history-detail').showModal();
    if (!item.available) return;
    try {
      const result = previews.get(item.id) || await image(item.id);
      if (version !== detailVersion) return;
      $('history-detail-image').src = result.image_data;
      $('history-detail-image').hidden = false;
      $('history-detail-status').textContent = '';
    } catch (error) {
      if (version === detailVersion) $('history-detail-status').textContent = error.message;
    }
  }

  function tile(item) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'history-tile';
    button.setAttribute('aria-label', `查看图片 ${item.sequence}`);
    const media = document.createElement('div');
    media.className = 'history-media';
    const placeholder = document.createElement('span');
    placeholder.textContent = item.available ? '加载中…' : '缓存已过期';
    media.append(placeholder);
    const info = document.createElement('div');
    info.className = 'history-tile-info';
    const label = document.createElement('strong');
    label.textContent = `${item.sequence} · ${modes[item.mode] || '图片'}`;
    const prompt = document.createElement('p');
    prompt.textContent = item.prompt || '未记录提示词';
    const stamp = document.createElement('small');
    stamp.textContent = `${date(item.created_at)}${item.provider ? ` · ${item.provider}` : ''}`;
    const session = document.createElement('small');
    session.className = 'history-session';
    session.textContent = `会话：${item.conversation_title || item.conversation || item.origin || '默认会话'}`;
    session.title = `${session.textContent}\n${item.origin || ''}\n用户：${item.sender || '未记录'}`;
    info.append(label, prompt, stamp, session);
    button.append(media, info);
    button.addEventListener('click', () => openDetail(item));
    return { item, button, media, placeholder };
  }

  async function load(force = false) {
    if (loaded && !force) return;
    loaded = true;
    const version = ++generation;
    previews.clear();
    $('history-grid').replaceChildren();
    $('history-status').textContent = '正在加载历史…';
    $('history-prev').disabled = $('history-next').disabled = true;
    $('history-count').textContent = '';
    try {
      await bridge.ready();
      const result = await bridge.apiGet('get_history', { page, query: $('history-query').value.trim() });
      if (version !== generation) return;
      if (!result.success) throw new Error(result.error || '历史读取失败，请刷新重试');
      page = result.page;
      pages = result.pages;
      $('history-count').textContent = `${result.total} 条记录`;
      $('history-page').textContent = `${page} / ${pages}`;
      $('history-status').textContent = result.items.length ? '' : '暂无匹配的生成记录';
      $('history-prev').disabled = page <= 1;
      $('history-next').disabled = page >= pages;
      const tiles = result.items.map(tile);
      $('history-grid').append(...tiles.map(entry => entry.button));
      // Bound concurrent preview requests and stop old pages from updating the new view.
      let cursor = 0;
      async function worker() {
        while (cursor < tiles.length && version === generation) {
          const entry = tiles[cursor++];
          if (!entry.item.available) continue;
          try {
            const result = await image(entry.item.id);
            if (version !== generation) return;
            previews.set(entry.item.id, result);
            const img = document.createElement('img');
            img.alt = `生成图片 #${entry.item.id}`;
            img.src = result.image_data;
            entry.media.replaceChildren(img);
          } catch (error) {
            if (version === generation) entry.placeholder.textContent = '预览不可用';
          }
        }
      }
      await Promise.all(Array.from({ length: 4 }, worker));
    } catch (error) {
      if (version !== generation) return;
      loaded = false;
      $('history-status').textContent = error.message;
      $('history-page').textContent = '';
    }
  }

  function bind() {
    $('history-search').addEventListener('submit', event => {
      event.preventDefault(); page = 1; load(true);
    });
    $('history-refresh').addEventListener('click', () => load(true));
    $('history-prev').addEventListener('click', () => { if (page > 1) { page--; load(true); } });
    $('history-next').addEventListener('click', () => { if (page < pages) { page++; load(true); } });
    $('history-close').addEventListener('click', () => $('history-detail').close());
    $('history-detail').addEventListener('close', () => {
      detailVersion++;
      $('history-detail-image').removeAttribute('src');
    });
    $('history-copy').addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(selected?.prompt || '');
        showToast('提示词已复制');
      } catch { showToast('复制失败，请选择提示词后复制', 'err'); }
    });
    $('history-download').addEventListener('click', async () => {
      const item = selected, version = detailVersion;
      if (!item?.available) return;
      $('history-download').disabled = true;
      $('history-detail-status').textContent = '正在读取原图…';
      try {
        const result = await image(item.id, true);
        if (version !== detailVersion) return;
        const link = document.createElement('a');
        link.href = result.image_data;
        link.download = result.filename;
        document.body.append(link);
        link.click();
        link.remove();
        $('history-detail-status').textContent = '';
      } catch (error) {
        if (version === detailVersion) $('history-detail-status').textContent = error.message;
      } finally {
        if (version === detailVersion) $('history-download').disabled = false;
      }
    });
  }
  return { load, bind };
}
