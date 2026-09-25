<script>
  import { onMount } from 'svelte'

  let username = 'processor'
  let password = 'herb123456'
  let token = localStorage.getItem('herb_token') || ''
  let role = localStorage.getItem('herb_role') || ''
  let view = location.hash === '#/location' ? 'location' : 'home'

  let rows = []
  let herb = '白芍'
  let tempC = 110
  let minutes = 10
  let locationCode = '甲仓/01'
  let error = ''

  // 入库货位
  let rule = null
  let ruleDraft = ''
  let ruleError = ''
  let ledger = []
  let fixInputs = {}
  let fixErrors = {}

  onMount(() => {
    const onHash = () => (view = location.hash === '#/location' ? 'location' : 'home')
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  })

  async function api(path, options = {}) {
    const res = await fetch(path, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.detail || '请求失败')
    return data
  }

  async function enter() {
    const data = await api('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
    token = data.access_token
    role = data.role
    localStorage.setItem('herb_token', token)
    localStorage.setItem('herb_role', role)
    await loadAll()
  }

  async function loadAll() {
    const [b, r, l] = await Promise.all([
      api('/api/batches'),
      api('/api/location/rule'),
      api('/api/location/ledger'),
    ])
    rows = b
    rule = r
    ruleDraft = r.warehouse
    ledger = l
  }

  async function save() {
    error = ''
    try {
      await api('/api/batches', {
        method: 'POST',
        body: JSON.stringify({
          herb,
          location_code: locationCode,
          steps: [{ name: '清炒', temp_c: Number(tempC), minutes: Number(minutes) }],
        }),
      })
      await loadAll()
    } catch (err) {
      error = err.message
    }
  }

  async function saveRule() {
    ruleError = ''
    try {
      rule = await api('/api/location/rule', {
        method: 'PUT',
        body: JSON.stringify({ warehouse: ruleDraft }),
      })
      ruleDraft = rule.warehouse
    } catch (err) {
      ruleError = err.message
    }
  }

  async function fixCode(entry) {
    fixErrors[entry.id] = ''
    const next = (fixInputs[entry.id] || '').trim()
    if (!next) {
      fixErrors[entry.id] = '请填写新货位码'
      fixErrors = fixErrors
      return
    }
    try {
      await api(`/api/batches/${entry.batch_id}/location`, {
        method: 'PUT',
        body: JSON.stringify({ location_code: next }),
      })
      fixInputs[entry.id] = ''
      await loadAll()
    } catch (err) {
      fixErrors[entry.id] = err.message
      fixErrors = fixErrors
    }
  }

  function fmtTime(t) {
    return t ? new Date(t).toLocaleString('zh-CN', { hour12: false }) : ''
  }

  function leave() {
    localStorage.clear()
    token = ''
    role = ''
  }

  if (token) loadAll()
</script>

<main>
  {#if !token}
    <h1>饮片炮制记录台</h1>
    <p>炮制记录整包保存。清炒温度须在 80 到 150，时长须在 5 到 30 分钟。入库货位码强制，格式为 汉字仓名/两位货架号。</p>
    <input bind:value={username} />
    <input type="password" bind:value={password} />
    <button on:click={enter}>登录</button>
    <p>processor / herb123456 可写；checker / check123456 只读</p>
  {:else}
    <nav class="topbar">
      <span class="brand">饮片炮制记录台</span>
      <a href="#/" class="navlink" class:on={view === 'home'}>炮制记录</a>
      <a href="#/location" class="navlink" class:on={view === 'location'}>入库货位</a>
      <button class="logout" on:click={leave}>退出</button>
    </nav>

    {#if view === 'home'}
      <section>
        <h2>炮制记录</h2>
        {#if role === 'writer'}
          <div class="writeform">
            <input bind:value={herb} placeholder="饮片" />
            <input type="number" bind:value={tempC} title="清炒温度" />
            <input type="number" bind:value={minutes} title="清炒时长(分)" />
            <input bind:value={locationCode} placeholder="货位码，如 甲仓/01" class="loc" />
            <button on:click={save}>写入清炒记录</button>
          </div>
          {#if error}<p class="err">{error}</p>{/if}
        {/if}
        <ul>
          {#each rows as row}
            <li>{row.herb} · {row.verdict} · {row.reason} · 温度 {row.doc.steps[0].temp_c} · 货位 {row.location_code}</li>
          {/each}
        </ul>
      </section>
    {:else}
      <section>
        <h2>入库货位</h2>

        <div class="card">
          <h3>规则设置</h3>
            {#if rule}
              <p>当前仓名：<strong>{rule.warehouse}</strong>
                （{rule.updated_by} 设于 {fmtTime(rule.updated_at)}）
              </p>
              <p class="hint">货位码须为「{rule.warehouse}/两位货架号」，例如 {rule.warehouse}/01；规则变更仅约束之后的提交。</p>
              {#if role === 'writer'}
                <input bind:value={ruleDraft} placeholder="汉字仓名，如 甲仓" />
                <button on:click={saveRule}>更新仓名规则</button>
                {#if ruleError}<p class="err">{ruleError}</p>{/if}
              {:else}
                <p class="hint">质检员可查阅规则，不可改规则。</p>
              {/if}
            {/if}
        </div>

        {#if role === 'writer'}
          <div class="card">
            <h3>写入时货位栏</h3>
            <div class="writeform">
              <input bind:value={herb} placeholder="饮片" />
              <input type="number" bind:value={tempC} title="清炒温度" />
              <input type="number" bind:value={minutes} title="清炒时长(分)" />
              <input bind:value={locationCode} placeholder="货位码，如 甲仓/01" class="loc" />
              <button on:click={save}>写入清炒记录</button>
            </div>
            {#if error}<p class="err">{error}</p>{/if}
          </div>
        {/if}

        <div class="card">
          <h3>货位流水</h3>
          <table>
            <thead>
              <tr>
                <th>时间</th><th>批次</th><th>饮片</th><th>动作</th><th>货位码</th><th>操作员</th>
                {#if role === 'writer'}<th>事后改正</th>{/if}
              </tr>
            </thead>
            <tbody>
              {#each ledger as entry}
                <tr>
                  <td>{fmtTime(entry.created_at)}</td>
                  <td>#{entry.batch_id}</td>
                  <td>{entry.herb}</td>
                  <td><span class="action" class:fix={entry.action === '改正'}>{entry.action}</span></td>
                  <td class="code">{entry.location_code}</td>
                  <td>{entry.operator}</td>
                  {#if role === 'writer'}
                    <td>
                      <input
                        class="fixinput"
                        placeholder="新货位码"
                        bind:value={fixInputs[entry.id]}
                      />
                      <button on:click={() => fixCode(entry)}>改正此行</button>
                      {#if fixErrors[entry.id]}<p class="err">{fixErrors[entry.id]}</p>{/if}
                    </td>
                  {/if}
                </tr>
              {/each}
            </tbody>
      </table>
          <p class="hint">流水只追加：改正会新增一条「改正」记录，早先的「写入」那条不会被改写。</p>
        </div>
      </section>
    {/if}
  {/if}
</main>

<style>
  main { font-family: sans-serif; max-width: 900px; margin: 24px auto; color: #3f2f1f; padding: 0 16px; }
  h1 { color: #7c2d12; }
  input { margin-right: 8px; padding: 6px; }
  .topbar {
    display: flex; align-items: center; gap: 16px;
    border-bottom: 2px solid #7c2d12; padding-bottom: 8px; margin-bottom: 16px;
  }
  .brand { font-weight: bold; color: #7c2d12; margin-right: auto; }
  .navlink { color: #7c2d12; text-decoration: none; font-weight: 500; }
  .navlink.on { text-decoration: underline; font-weight: bold; }
  .logout { padding: 4px 10px; }
  .writeform { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .loc { min-width: 150px; }
  .card { border: 1px solid #d6c3b0; border-radius: 6px; padding: 12px 16px; margin: 16px 0; }
  .card h3 { margin-top: 4px; color: #7c2d12; }
  .hint { color: #7a6a5a; font-size: 13px; }
  .err { color: #b91c1c; }
  table { border-collapse: collapse; width: 100%; font-size: 14px; }
  th, td { border: 1px solid #e2d6c8; padding: 6px 8px; text-align: left; }
  th { background: #faf3ec; }
  .code { font-family: monospace; }
  .action.fix { color: #b45309; font-weight: bold; }
  .fixinput { width: 110px; }
</style>
