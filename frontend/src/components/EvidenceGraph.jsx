import { useEffect, useRef, useState } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { api } from '../api.js'

const TYPE_COLORS = {
  person: '#8c2f26',
  location: '#2f4a3c',
  object: '#c9a24b',
  organization: '#3a2e22',
}

export default function EvidenceGraph() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const containerRef = useRef(null)
  const [dims, setDims] = useState({ width: 800, height: 460 })

  useEffect(() => {
    api
      .getGraph()
      .then((raw) => {
        const nodes = (raw.nodes || []).map((n) => ({
          id: n.id ?? n.entity_id,
          name: n.name || n.id,
          type: n.type || 'person',
        }))
        const links = (raw.links || raw.edges || []).map((e) => ({
          source: e.source,
          target: e.target,
          relation: e.relation || e.relationship || '',
        }))
        setData({ nodes, links })
      })
      .catch((e) => setError(e.message))
  }, [])

  useEffect(() => {
    function onResize() {
      if (containerRef.current) {
        setDims({ width: containerRef.current.offsetWidth, height: 470 })
      }
    }
    onResize()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  return (
    <section>
      <div className="section-title">
        <span>The Corkboard</span>
        <span className="stamp-small">entities &amp; relationships</span>
      </div>

      {error && (
        <p className="error-note">
          Couldn't load the graph ({error}). Make sure /ingest has run and graph.json is being served.
        </p>
      )}

      <div className="corkboard" ref={containerRef}>
        {data && (
          <ForceGraph2D
            width={dims.width}
            height={dims.height}
            graphData={data}
            backgroundColor="rgba(0,0,0,0)"
            linkColor={() => '#8c2f26'}
            linkWidth={1.5}
            linkDirectionalArrowLength={4}
            linkLabel={(l) => l.relation}
            nodeRelSize={5}
            nodeCanvasObject={(node, ctx, globalScale) => {
              const label = node.name
              const fontSize = 12 / globalScale
              ctx.beginPath()
              ctx.arc(node.x, node.y, 7, 0, 2 * Math.PI)
              ctx.fillStyle = TYPE_COLORS[node.type] || '#c9a24b'
              ctx.fill()
              ctx.strokeStyle = '#171310'
              ctx.lineWidth = 1.5
              ctx.stroke()
              ctx.font = `${fontSize}px 'Special Elite', monospace`
              ctx.fillStyle = '#ede3cc'
              ctx.textAlign = 'center'
              ctx.fillText(label, node.x, node.y + 16)
            }}
          />
        )}
        <div className="graph-legend">
          {Object.entries(TYPE_COLORS).map(([type, color]) => (
            <div key={type} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: color, display: 'inline-block' }} />
              {type}
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
