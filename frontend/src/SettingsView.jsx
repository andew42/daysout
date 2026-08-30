import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchGeocode } from './api.jsx'
import { ALL_CATEGORIES, loadSettings, saveSettings } from './settings.jsx'

export default function SettingsView() {
  const [settings, setSettings] = useState(loadSettings)
  const [checkResult, setCheckResult] = useState('')
  const navigate = useNavigate()

  // Persist as you go, except the postcode, which is only worth keeping
  // once it geocodes. A slider that moved on screen but saved nothing
  // until the Save button was pressed left the app running on the old
  // limit while showing the new one — the setting looked applied and was
  // not, which is indistinguishable from the filter being broken.
  const update = patch => setSettings(s => {
    const next = { ...s, ...patch }
    if (!('postcode' in patch)) saveSettings(next)
    return next
  })

  const toggleCategory = id =>
    update({
      categories: settings.categories.includes(id)
        ? settings.categories.filter(c => c !== id)
        : [...settings.categories, id],
    })

  const save = async event => {
    event.preventDefault()
    setCheckResult('')
    try {
      await fetchGeocode(settings.postcode)
    } catch (e) {
      setCheckResult(e.message)
      return
    }
    saveSettings(settings)
    navigate('/')
  }

  return (
    <form className="settings-view" onSubmit={save}>
      <h2>Settings</h2>

      <label>
        Home postcode
        <input
          type="text"
          value={settings.postcode}
          onChange={e => update({ postcode: e.target.value })}
          placeholder="e.g. SN13 8AA"
          autoFocus
        />
      </label>
      {checkResult && <p className="notice error">{checkResult}</p>}

      <label>
        Maximum drive time: {settings.minutes} minutes
        <input
          type="range" min="15" max="180" step="15"
          value={settings.minutes}
          onChange={e => update({ minutes: Number(e.target.value) })}
        />
      </label>

      <label>
        Events look-ahead: {settings.days} days
        <input
          type="range" min="1" max="30" step="1"
          value={settings.days}
          onChange={e => update({ days: Number(e.target.value) })}
        />
      </label>

      <fieldset>
        <legend>Categories</legend>
        {ALL_CATEGORIES.map(category => (
          <label key={category.id} className="checkbox">
            <input
              type="checkbox"
              checked={settings.categories.includes(category.id)}
              onChange={() => toggleCategory(category.id)}
            />
            {category.label}
          </label>
        ))}
      </fieldset>

      <button type="submit">Save postcode</button>
      <p className="notice">
        Drive time, look-ahead and categories apply as you change them.
      </p>
    </form>
  )
}
