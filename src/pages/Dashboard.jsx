import { useMemo, useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { useAppContext } from '../App';
import FraudRingTable from '../components/FraudRingTable';
import MiniGraph from '../components/MiniGraph';
import RiskGauge from '../components/RiskGauge';

function AnimatedNumber({ value, duration = 1200 }) {
    const [display, setDisplay] = useState(0);
    useEffect(() => {
        const num = typeof value === 'number' ? value : parseFloat(value) || 0;
        const start = performance.now();
        const step = (now) => {
            const p = Math.min((now - start) / duration, 1);
            const eased = 1 - Math.pow(1 - p, 3);
            setDisplay(Math.round(eased * num));
            if (p < 1) requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
    }, [value, duration]);
    return <>{display.toLocaleString()}</>;
}

const stagger = { hidden: {}, visible: { transition: { staggerChildren: 0.08 } } };
const fadeUp = { hidden: { opacity: 0, y: 20 }, visible: { opacity: 1, y: 0, transition: { duration: 0.5 } } };

export default function Dashboard() {
    const { result, graphData } = useAppContext();
    const navigate = useNavigate();
    const s = result?.summary;

    const stats = useMemo(() => {
        if (!result) return null;
        const accounts = result.suspicious_accounts || [];
        const rings = result.fraud_rings || [];
        const highRisk = accounts.filter(a => a.suspicion_score > 70).length;
        const avgScore = accounts.length > 0
            ? (accounts.reduce((sum, a) => sum + a.suspicion_score, 0) / accounts.length).toFixed(1)
            : '0.0';
        const totalRingMembers = rings.reduce((sum, r) => sum + r.member_accounts.length, 0);
        return { highRisk, avgScore, totalRingMembers, accounts, rings };
    }, [result]);

    if (!result) {
        navigate('/');
        return null;
    }

    return (
        <div className="max-w-[1560px] mx-auto px-6 py-6">
            {/* Header */}
            <motion.div
                className="mb-8"
                initial={{ opacity: 0, y: -10 }}
                animate={{ opacity: 1, y: 0 }}
            >
                <h1 style={{ fontFamily: 'var(--font-mono)', fontWeight: 800, fontSize: '1.4rem', letterSpacing: '0.1em' }}>
                    <span style={{ color: 'var(--color-accent)' }}>THREAT</span> DASHBOARD
                </h1>
                <p style={{ color: 'var(--color-text-dim)', fontSize: '0.75rem', marginTop: '4px' }}>
                    Hybrid Sentinel v6.0 — Real-time Financial Crime Intelligence
                </p>
            </motion.div>

            {/* Metric Cards - Bento Grid */}
            <motion.div
                className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4 mb-8"
                variants={stagger}
                initial="hidden"
                animate="visible"
            >
                <motion.div className="metric-card glass-card-glow" variants={fadeUp}>
                    <div className="metric-value"><AnimatedNumber value={s.total_accounts_analyzed} /></div>
                    <div className="metric-label">Total Accounts</div>
                </motion.div>

                <motion.div className="metric-card glass-card-glow" variants={fadeUp}>
                    <div className="metric-value danger"><AnimatedNumber value={s.suspicious_accounts_flagged} /></div>
                    <div className="metric-label">Suspicious Accounts</div>
                </motion.div>

                <motion.div className="metric-card glass-card-glow" variants={fadeUp}>
                    <div className="metric-value warning"><AnimatedNumber value={stats.highRisk} /></div>
                    <div className="metric-label">High Risk Mules</div>
                </motion.div>

                <motion.div className="metric-card glass-card-glow" variants={fadeUp}>
                    <div className="metric-value"><AnimatedNumber value={s.fraud_rings_detected} /></div>
                    <div className="metric-label">Fraud Rings</div>
                </motion.div>

                <motion.div className="metric-card glass-card-glow" variants={fadeUp}>
                    <div className="metric-value success">{stats.avgScore}</div>
                    <div className="metric-label">Avg Fraud Score</div>
                </motion.div>
            </motion.div>

            {/* Bento Layout: Fraud Ring Summary + Graph + Gauge */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 mb-8">
                {/* Fraud Ring Summary */}
                <motion.div
                    className="lg:col-span-2 glass-card p-5"
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.3 }}
                >
                    <div className="flex items-center justify-between mb-4">
                        <h2 style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '0.9rem', color: 'var(--color-text-primary)', letterSpacing: '0.06em' }}>
                            FRAUD RING SUMMARY
                        </h2>
                        <span className="badge badge-high">{result.fraud_rings.length} rings</span>
                    </div>
                    <FraudRingTable rings={result.fraud_rings} />
                </motion.div>

                {/* Right Column: Mini Graph + Gauge */}
                <motion.div
                    className="flex flex-col gap-5"
                    initial={{ opacity: 0, x: 20 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: 0.4 }}
                >
                    {/* Mini Transaction Network */}
                    <div
                        className="glass-card p-4 cursor-pointer"
                        onClick={() => navigate('/graph')}
                        style={{ flex: 1 }}
                    >
                        <h3 style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '0.75rem', color: 'var(--color-text-secondary)', marginBottom: '8px', letterSpacing: '0.06em' }}>
                            TRANSACTION NETWORK
                        </h3>
                        <div className="graph-container" style={{ height: '180px' }}>
                            <MiniGraph data={graphData} />
                        </div>
                        <p style={{ color: 'var(--color-text-dim)', fontSize: '0.65rem', textAlign: 'center', marginTop: '8px', fontFamily: 'var(--font-mono)' }}>
                            Click to expand →
                        </p>
                    </div>

                    {/* Risk Gauge */}
                    <div className="glass-card p-5 flex flex-col items-center justify-center">
                        <h3 style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '0.75rem', color: 'var(--color-text-secondary)', marginBottom: '12px', letterSpacing: '0.06em' }}>
                            THREAT LEVEL
                        </h3>
                        <RiskGauge score={parseFloat(stats.avgScore)} />
                    </div>
                </motion.div>
            </div>

            {/* Top Suspicious Accounts Preview */}
            <motion.div
                className="glass-card p-5 mb-8"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.5 }}
            >
                <div className="flex items-center justify-between mb-4">
                    <h2 style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '0.9rem', letterSpacing: '0.06em' }}>
                        TOP SUSPICIOUS ACCOUNTS
                    </h2>
                    <button
                        className="btn-primary"
                        style={{ padding: '6px 14px', fontSize: '0.7rem' }}
                        onClick={() => navigate('/transactions')}
                    >
                        View All →
                    </button>
                </div>
                <div className="overflow-x-auto">
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>Account ID</th>
                                <th>Score</th>
                                <th>Patterns</th>
                                <th>Ring</th>
                                <th>Explanation</th>
                            </tr>
                        </thead>
                        <tbody>
                            {(result.suspicious_accounts || []).slice(0, 8).map((a) => (
                                <tr key={a.account_id}>
                                    <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '0.75rem' }}>{a.account_id}</td>
                                    <td>
                                        <span className={`badge ${a.suspicion_score > 70 ? 'badge-high' : a.suspicion_score > 30 ? 'badge-medium' : 'badge-low'}`}>
                                            {a.suspicion_score}
                                        </span>
                                    </td>
                                    <td>
                                        <div className="flex flex-wrap gap-1">
                                            {a.detected_patterns.map((p) => (
                                                <span key={p} className="pattern-chip">{p}</span>
                                            ))}
                                        </div>
                                    </td>
                                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: 'var(--color-accent)' }}>
                                        {a.ring_id || '—'}
                                    </td>
                                    <td style={{ fontSize: '0.7rem', color: 'var(--color-text-dim)', maxWidth: '250px' }}>
                                        {a.explanation || '—'}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </motion.div>

            {/* Bottom: Quick Stats */}
            <motion.div
                className="grid grid-cols-2 md:grid-cols-4 gap-4"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.6 }}
            >
                <div className="glass-card p-4 text-center">
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '1.4rem', fontWeight: 700, color: 'var(--color-accent)' }}>
                        {stats.totalRingMembers}
                    </div>
                    <div className="metric-label">Accounts in Rings</div>
                </div>
                <div className="glass-card p-4 text-center">
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '1.4rem', fontWeight: 700, color: 'var(--color-risk-orange)' }}>
                        {result.fraud_rings.filter(r => r.pattern_type === 'smurfing').length}
                    </div>
                    <div className="metric-label">Smurf Rings</div>
                </div>
                <div className="glass-card p-4 text-center">
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '1.4rem', fontWeight: 700, color: 'var(--color-risk-red)' }}>
                        {result.fraud_rings.filter(r => r.pattern_type === 'cycle').length}
                    </div>
                    <div className="metric-label">Cycle Rings</div>
                </div>
                <div className="glass-card p-4 text-center">
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '1.4rem', fontWeight: 700, color: 'var(--color-text-secondary)' }}>
                        {`${s.processing_time_seconds.toFixed(2)}s`}
                    </div>
                    <div className="metric-label">Processing Time</div>
                </div>
            </motion.div>
        </div>
    );
}
