import { useLocation, Link } from 'react-router-dom';

const links = [
    { to: '/dashboard', label: 'Dashboard', icon: '◈' },
    { to: '/graph', label: 'Network Graph', icon: '⬡' },
    { to: '/transactions', label: 'Transactions', icon: '▤' },
    { to: '/risk', label: 'Risk Analysis', icon: '◉' },
];

export default function Navbar() {
    const { pathname } = useLocation();

    return (
        <nav className="nav-bar">
            <div className="max-w-[1560px] mx-auto px-6 flex items-center justify-between h-14">
                <Link to="/dashboard" className="flex items-center gap-2 no-underline">
                    <span style={{ color: 'var(--color-accent)', fontFamily: 'var(--font-mono)', fontWeight: 800, fontSize: '0.85rem', letterSpacing: '0.1em' }}>
                        MONEY<span style={{ color: 'var(--color-text-primary)' }}>MAL</span>
                    </span>
                    <span style={{ color: 'var(--color-text-dim)', fontSize: '0.65rem', fontFamily: 'var(--font-mono)' }}>v6.0</span>
                </Link>
                <div className="flex items-center gap-1">
                    {links.map((l) => (
                        <Link
                            key={l.to}
                            to={l.to}
                            className={`nav-link flex items-center gap-1.5 ${pathname === l.to ? 'active' : ''}`}
                        >
                            <span style={{ fontSize: '0.7rem' }}>{l.icon}</span>
                            {l.label}
                        </Link>
                    ))}
                </div>
            </div>
        </nav>
    );
}
