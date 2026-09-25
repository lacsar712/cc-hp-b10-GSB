<script>
  let username = 'processor'
  let password = 'herb123456'
  let token = localStorage.getItem('herb_token') || ''
  let role = localStorage.getItem('herb_role') || ''
  let name = localStorage.getItem('herb_user') || ''
  let view = 'records'
  let rows = []
  let rule = null
  let ledger = []
  let herb = '白芍'
  let tempC = 110
  let minutes = 10
  let locationCode = ''
  let ruleWarehouse = ''
  let ruleDigits = 2
  let correctDraft = {}
  let error = ''
  let ruleMsg = ''
  let correctError = ''

  async function api(path, options = {}) {
    const res = await fetch(path, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) {
      const msg = Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join('；') : data.detail
      throw new Error(msg || '请求失败')
    }
    return data
  }

  async function enter() {
    const data = await api('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
    token = data.access_token
    role = data.role
    name = data.username
    localStorage.setItem('herb_token', token)
    localStorage.setItem('herb_role', role)
    localStorage.setItem('herb_user', name)
    view = 'records'
    await load()
  }

  async function load() {
    rows = await api('/api/batches')
  }

  async function loadLocation() {
    rule = await api('/api/location/rule')
    ruleWarehouse = rule.warehouse_name
    ruleDigits = rule.shelf_digits
    ledger = await api('/api/location/ledger')
    rows = await api('/api/batches')
  }

  function show(next) {
    view = next
    error = ''
    if (next === 'location') loadLocation().catch((err) => (error = err.message))
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
      locationCode = ''
      await loadLocation()
    } catch (err) {
      error = err.message
    }
  }

  async function saveRule() {
    ruleMsg = ''
    try {
      rule = await api('/api/location/rule', {
        method: 'PUT',
        body: JSON.stringify({ warehouse_name: ruleWarehouse, shelf_digits: Number(ruleDigits) }),
      })
      ruleMsg = `规则已更新为 ${rule.example}，仅约束后续提交`
    } catch (err) {
      ruleMsg = err.message
    }
  }

  async function correct(id) {
    correctError = ''
    try {
      await api(`/api/batches/${id}/location`, {
        method: 'PATCH',
        body: JSON.stringify({ location_code: correctDraft[id] || '' }),
      })
      correctDraft[id] = ''
      await loadLocation()
    } catch (err) {
      correctError = err.message
    }
  }

  function fmt(t) {
    return new Date(t).toLocaleString('zh-CN', { hour12: false })
  }

  function leave() {
    localStorage.clear()
    token = ''
    role = ''
    name = ''
    view = 'records'
    ledger = []
    rule = null
  }

  if (token) load()
</script>

<main>
  <h1>饮片炮制记录台</h1>
  {#if !token}
    <p>炮制记录整包保存。清炒温度须在 80 到 150，时长须在 5 到 30 分钟。</p>
    <input bind:value={username} />
    <input type="password" bind:value={password} />
    <button on:click={enter}>登录</button>
    <p>processor / herb123456 可写；checker / check123456 只读</p>
  {:else}
    <nav>
      <button class:active={view === 'records'} on:click={() => show('records')}>炮制记录</button>
      <button class:active={view === 'location'} on:click={() => show('location')}>入库货位</button>
      <span class="who">{name}（{role === 'writer' ? '炮制员' : '质检员'}）</span>
      <button on:click={leave}>退出</button>
    </nav>

    {#if view === 'records'}
      <ul>
        {#each rows as row}
          <li>{row.herb} · {row.verdict} · {row.reason} · 温度 {row.doc.steps[0].temp_c}</li>
        {/each}
      </ul>
    {:else}
      <section>
        <h2>规则设置</h2>
        {#if rule}
          <p>当前规则：汉字仓名 + 斜线 + {rule.shelf_digits} 位货架号，示例 <code>{rule.example}</code>。规则变更仅约束后续提交。</p>
          {#if role === 'writer'}
            <input bind:value={ruleWarehouse} placeholder="汉字仓名，如 甲仓" />
            <select bind:value={ruleDigits}>
              <option value={1}>1 位货架号</option>
              <option value={2}>2 位货架号</option>
              <option value={3}>3 位货架号</option>
              <option value={4}>4 位货架号</option>
            </select>
            <button on:click={saveRule}>保存规则</button>
            {#if ruleMsg}<p>{ruleMsg}</p>{/if}
          {:else}
            <p>质检员可查阅规则与流水，不可修改规则。</p>
          {/if}
        {/if}
      </section>

      {#if role === 'writer'}
        <section>
          <h2>写入记录</h2>
          <input bind:value={herb} placeholder="饮片" />
          <input type="number" bind:value={tempC} />
          <input type="number" bind:value={minutes} />
          <input bind:value={locationCode} placeholder={rule ? `货位码，如 ${rule.example}` : '货位码'} />
          <button on:click={save}>写入清炒记录</button>
          {#if error}<p class="err">{error}</p>{/if}
        </section>

        <section>
          <h2>货位改正</h2>
          <table>
            <thead>
              <tr><th>单号</th><th>饮片</th><th>当前货位</th><th>改正为</th><th></th></tr>
            </thead>
            <tbody>
              {#each rows as row}
                <tr>
                  <td>{row.id}</td>
                  <td>{row.herb}</td>
                  <td>{row.location_code || '—'}</td>
                  <td><input bind:value={correctDraft[row.id]} placeholder={rule ? rule.example : '货位码'} /></td>
                  <td><button on:click={() => correct(row.id)}>改正</button></td>
                </tr>
              {/each}
            </tbody>
          </table>
          {#if correctError}<p class="err">{correctError}</p>{/if}
        </section>
      {/if}

      <section>
        <h2>货位流水</h2>
        <table>
          <thead>
            <tr><th>时间</th><th>单号</th><th>饮片</th><th>货位码</th><th>动作</th><th>操作人</th></tr>
          </thead>
          <tbody>
            {#each ledger as entry}
              <tr>
                <td>{fmt(entry.created_at)}</td>
                <td>{entry.batch_id}</td>
                <td>{entry.herb}</td>
                <td>{entry.location_code}</td>
                <td>{entry.action}</td>
                <td>{entry.created_by}</td>
              </tr>
            {/each}
          </tbody>
        </table>
        {#if ledger.length === 0}<p>暂无流水。</p>{/if}
      </section>
    {/if}
  {/if}
</main>

<style>
  main { font-family: sans-serif; max-width: 720px; margin: 24px auto; color: #3f2f1f; }
  h1 { color: #7c2d12; }
  h2 { font-size: 18px; color: #7c2d12; margin-bottom: 8px; }
  input { margin-right: 8px; padding: 6px; }
  nav { display: flex; align-items: center; gap: 8px; border-bottom: 2px solid #e7d8c9; padding-bottom: 10px; margin-bottom: 16px; }
  nav .who { margin-left: auto; color: #8a6d52; }
  nav button.active { background: #7c2d12; color: #fff; }
  section { border: 1px solid #e7d8c9; border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; }
  table { border-collapse: collapse; width: 100%; }
  th, td { border-bottom: 1px solid #e7d8c9; text-align: left; padding: 6px 8px; font-size: 14px; }
  code { background: #f5ede3; padding: 1px 6px; border-radius: 4px; }
  .err { color: #b91c1c; }
</style>
