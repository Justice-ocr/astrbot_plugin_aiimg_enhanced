export function createOperationsController({ $, bridge, showToast }) {
  let tab = '', timer = null, loading = false;
  const states = {
    preparing: '准备中', generating: '生成中', downloading: '下载中', sending: '发送中',
    cancelling: '取消中', completed: '已完成', partial: '部分完成', failed: '失败', cancelled: '已取消',
  };
  const terminal = new Set(['completed', 'partial', 'failed', 'cancelled']);
  const text = (tag, value, className = '') => {
    const element = document.createElement(tag);
    element.textContent = value;
    element.className = className;
    return element;
  };

  async function tasks() {
    if (loading) return;
    loading = true;
    try {
      const result = await bridge.apiGet('get_tasks');
      if (!result.success) throw new Error(result.error || '任务读取失败');
      if (tab !== 'tab-tasks') return;
      $('tasks-list').replaceChildren();
      $('tasks-status').textContent = result.items.length ? '' : '暂无任务';
      for (const item of result.items) {
        const row = text('article', '', 'operations-row');
        const info = text('div', '', 'operations-info');
        info.append(
          text('strong', `${item.id} · ${states[item.state] || item.state}`),
          text('p', item.prompt),
          text('small', `${item.origin} · ${item.conversation || '默认会话'} · ${item.sender}`),
          text('small', `${new Date(item.created_at * 1000).toLocaleString()} · ${item.persona} · 已生成 ${item.generated} / 已发送 ${item.sent}`),
        );
        if (item.error) info.append(text('p', item.error, 'operations-error'));
        row.append(info);
        if (!terminal.has(item.state)) {
          const cancel = text('button', '取消', 'btn-danger');
          cancel.type = 'button';
          cancel.disabled = item.state === 'cancelling';
          cancel.setAttribute('aria-label', `取消任务 ${item.id}`);
          cancel.addEventListener('click', async () => {
            if (!confirm('取消本地任务？上游已提交的请求可能仍会生成并计费。')) return;
            cancel.disabled = true;
            try {
              const response = await bridge.apiPost('cancel_task', { id: item.id });
              if (!response.success) throw new Error(response.error || '取消失败');
              await tasks();
            } catch (error) { showToast(error.message, 'err'); cancel.disabled = false; }
          });
          row.append(cancel);
        }
        $('tasks-list').append(row);
      }
    } catch (error) { $('tasks-status').textContent = error.message; }
    finally { loading = false; }
  }

  async function sessions() {
    $('sessions-status').textContent = '正在加载…';
    try {
      const result = await bridge.apiGet('get_session_personas');
      if (!result.success) throw new Error(result.error || '会话读取失败');
      $('sessions-list').replaceChildren();
      $('sessions-status').textContent = result.items.length ? '' : '暂无会话记录';
      for (const item of result.items) {
        const row = text('div', '', 'operations-row');
        const info = text('div', '', 'operations-info');
        info.append(text('strong', item.title || item.conversation || '默认会话'),
          text('small', `${item.origin} · ${item.bot}`));
        const select = document.createElement('select');
        select.className = 'sel';
        select.setAttribute('aria-label', `会话人设 ${item.title || item.conversation || item.origin}`);
        for (const persona of [{id:'', name:'跟随全局默认'}, ...result.personas]) {
          const option = text('option', persona.name);
          option.value = persona.id;
          select.append(option);
        }
        select.value = item.persona_id;
        select.addEventListener('change', async () => {
          select.disabled = true;
          try {
            const response = await bridge.apiPost('set_session_persona', {
              scope: item.scope, persona_id: select.value,
            });
            if (!response.success) throw new Error(response.error || '切换失败');
            item.persona_id = select.value;
            showToast('会话人设已更新');
          } catch (error) { select.value = item.persona_id; showToast(error.message, 'err'); }
          finally { select.disabled = false; }
        });
        row.append(info, select);
        $('sessions-list').append(row);
      }
    } catch (error) { $('sessions-status').textContent = error.message; }
  }
  return {
    activate(next) {
      tab = next;
      clearInterval(timer);
      if (tab === 'tab-persona') sessions();
      if (tab === 'tab-tasks') {
        tasks();
        timer = setInterval(() => { if (!document.hidden) tasks(); }, 3000);
      }
    },
    bind() {
      $('tasks-refresh').addEventListener('click', tasks);
      $('sessions-refresh').addEventListener('click', sessions);
      window.addEventListener('pagehide', () => clearInterval(timer));
    },
  };
}
