export default function FraudRingTable({ rings }) {
    if (!rings || rings.length === 0) {
        return (
            <div style={{ textAlign: 'center', padding: 20, color: 'var(--color-text-dim)', fontFamily: 'var(--font-mono)', fontSize: '0.75rem' }}>
                No fraud rings detected
            </div>
        );
    }

    return (
        <div style={{ maxHeight: 350, overflow: 'auto' }}>
            <table className="data-table">
                <thead>
                    <tr>
                        <th>Ring ID</th>
                        <th>Members</th>
                        <th>Pattern Type</th>
                        <th>Risk Score</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    {rings.map((ring) => (
                        <tr key={ring.ring_id}>
                            <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '0.78rem', color: 'var(--color-accent)' }}>
                                {ring.ring_id}
                            </td>
                            <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '0.8rem' }}>
                                {ring.member_accounts.length}
                            </td>
                            <td>
                                <span className="pattern-chip">{ring.pattern_type}</span>
                            </td>
                            <td>
                                <div className="flex items-center gap-2">
                                    <div style={{ width: 80, height: 6, background: 'rgba(0,245,255,0.08)', borderRadius: 3, overflow: 'hidden' }}>
                                        <div
                                            style={{
                                                height: '100%',
                                                width: `${ring.risk_score}%`,
                                                borderRadius: 3,
                                                background: ring.risk_score > 80 ? 'var(--color-risk-red)' : ring.risk_score > 50 ? 'var(--color-risk-orange)' : 'var(--color-risk-green)',
                                                transition: 'width 0.5s',
                                            }}
                                        />
                                    </div>
                                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', fontWeight: 600, color: ring.risk_score > 80 ? 'var(--color-risk-red)' : 'var(--color-text-secondary)' }}>
                                        {ring.risk_score}%
                                    </span>
                                </div>
                            </td>
                            <td>
                                <span className={`badge ${ring.risk_score > 80 ? 'badge-high' : ring.risk_score > 50 ? 'badge-medium' : 'badge-low'}`}>
                                    {ring.risk_score > 80 ? 'Critical' : ring.risk_score > 50 ? 'Warning' : 'Low'}
                                </span>
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}
