"""First-class adapters that drop riskkit into popular backtesting frameworks.

Each adapter lives in its own module and imports its framework lazily, so the
riskkit core stays dependency-free. Import the one you need directly::

    from riskkit.adapters.backtesting import RiskkitStrategy
"""
