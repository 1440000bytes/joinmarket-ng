# Frequently Asked Questions

Bitcoin privacy is not a switch that software can flip. It depends on who is
watching, what else they know, and what happens before and after a transaction.
These answers are deliberately short; follow the links when a question matters
to your threat model.

## Bitcoin and CoinJoin Privacy

### Why do we need privacy if Bitcoin is pseudonymous?

An address is a pseudonym, not an identity shield. Every transaction, amount,
and on-chain link is public forever. Address reuse, common-input ownership,
change detection, timing, and known exchange withdrawals can connect a pseudonym
to other coins or to a person. Each heuristic can be wrong, but several weak
clues can become strong when combined.

Start with the [Bitcoin Wiki privacy guide](https://en.bitcoin.it/wiki/Privacy)
and the transaction-graph study
[A Fistful of Bitcoins](https://doi.org/10.1145/2504730.2504747).

### What does a CoinJoin hide?

A CoinJoin makes one transaction from inputs owned by several participants. In
an equal-output CoinJoin, an outside observer sees all inputs and outputs but
cannot directly read which participant received which equal output. It creates
competing ownership interpretations; it does not hide the transaction, its
amounts, or its existence.

See [Concepts](technical/concepts.md#what-is-coinjoin) for the JoinMarket form of
the transaction.

### Does CoinJoin make coins untraceable?

No. Change, distinctive amounts, timing, later consolidation, address reuse,
network data, and information held by counterparties can all narrow the
possibilities. CoinJoin can defeat useful tracing assumptions, but it does not
promise anonymity against every observer.

The archived reference guide makes the same warning about
[relying on one CoinJoin](https://github.com/JoinMarket-Org/joinmarket-clientserver/blob/v0.9.12/docs/USAGE.md#try-out-a-coinjoin-using-sendpaymentpy).

### How should on-chain privacy be measured?

Not by looking at one transaction or by equating the number of equal outputs
with guaranteed anonymity. Ask which ownership assignments remain plausible to
a particular observer after considering the full transaction graph, protocol
knowledge, prior probabilities, and auxiliary data. A later spend can make an
earlier ambiguity much less useful.

For a rigorous treatment, read
[Collaborative Transaction Privacy](https://gist.github.com/nothingmuch/d84ba390d89b5b08897af2d95009c2a1)
and its more experimental
[follow-up on breaking links across slots](https://gist.github.com/nothingmuch/f5b9a559958c6116606d9da0d4d884f2).

### How many CoinJoins are enough?

There is no universal number. More independent rounds and participants can add
ambiguity, but later merging, matching amounts, or predictable timing can give
it back. The useful question is whether your complete spending path resists the
observer in your threat model, not whether a round counter reached a target.

For an automated multi-round strategy, see the
[tumbler](README-tumbler.md#why-a-tumbler-privacy-rationale).

## JoinMarket's Model

### Why use JoinMarket instead of a mixer or a central coordinator?

A custodial mixer takes control of funds and can steal them or record the
deposit-withdrawal mapping. Non-custodial, coordinator-based CoinJoin protocols
avoid the custody problem, but a persistent coordinator can still occupy a
privileged observation or censorship position, depending on the protocol.

JoinMarket has no global CoinJoin coordinator. Each taker chooses makers and
constructs its own transaction. Directory servers help peers discover and reach
one another; they do not choose every round. This removes a system-wide vantage
point, although the taker coordinating one round necessarily learns that
round's maker submissions. See [JoinMarket's design](technical/concepts.md#why-joinmarket-is-different)
and the [JAM philosophy](https://jamdocs.org/philosophy/03-joinmarket/).

### What are makers and takers?

A **maker** keeps liquidity online, publishes offers, joins transactions when
selected, and earns a fee. A **taker** wants a CoinJoin now, selects offers,
coordinates the transaction, and pays the makers and the mining fee. Roles are
temporary: the same wallet can take in one transaction and make in another.

See [Concepts](technical/concepts.md#makers-and-takers), the
[maker guide](README-maker.md), and the [taker guide](README-taker.md).

### Does JoinMarket ever take custody of my bitcoin?

No central service receives the participants' keys or takes custody. Each
participant signs only its own inputs, and a maker verifies that the proposed
transaction returns the expected equal output, change, and fee before signing.
That removes custodian risk, not wallet, software, backup, or endpoint risk.

The checks are documented in the
[maker verification checklist](technical/maker-verification-checklist.md).

### What fees does a taker pay?

A taker pays the selected makers' advertised CoinJoin fees and the Bitcoin
mining fee for the complete transaction. More makers and inputs usually mean a
larger transaction. A maker earns its offer fee, but earnings and selection are
not guaranteed.

See the [taker configuration guide](README-taker.md#configuration-notes) and
[JAM's fee explanation](https://jamdocs.org/market/fees/).

### What are fidelity bonds?

A fidelity bond is a time-locked UTXO a maker publicly proves it controls.
Takers can favor makers with costly bonds, making it more expensive for one
operator to fill the orderbook with fake identities. The bond is also a public
linkage point, so its funding history deserves careful coin control.

See [Privacy: Fidelity Bonds](technical/privacy.md#fidelity-bonds) and the
[operations guide](fidelity-bond-operations.md).

### How is JoinMarket NG different from the reference implementation?

JoinMarket NG is an independent, modern implementation of the same protocol.
It is wire-compatible with the reference network, so compatible makers and
takers share liquidity, but its CLI, wallet files, backends, architecture, and
some optional features differ. Do not use reference wallet files or commands as
if they were JoinMarket NG files or commands.

See the maintained [compatibility overview](technical/overview.md) and
[wallet format notes](technical/architecture.md#wallet-file-formats).

## Coins, Roles, and Wallets

### Why are equal outputs special, and what is change?

Every participant receives an output of the same CoinJoin amount. Those equal
outputs form the transaction's main ambiguity. Inputs rarely total exactly that
amount, so the remainder returns as change; its distinct value and later spends
can help an observer connect activity across rounds. Treat an equal output and
its linkable change as different privacy classes.

JoinMarket NG labels both explicitly; see
[address status labels](technical/wallet.md#address-status-labels).

### What are mixdepths?

Mixdepths are separate accounts inside one wallet. An internal CoinJoin moves
the equal output to the next mixdepth while change remains behind. The boundary
prevents the wallet from immediately spending a private candidate together with
its more linkable change.

They are privacy compartments, not a score or proof that coins are mixed. See
[Privacy: Mixdepths](technical/privacy.md#mixdepths).

### Should I consolidate UTXOs?

Only when you accept the resulting link. Spending several UTXOs together is
evidence that one entity controls them, so consolidating across mixdepths or
unrelated histories can undo useful separation. Fee savings do not make that
privacy cost disappear.

Within one mixdepth, a sweep spends the entire selected balance without creating
taker change. That can end a peel chain, but it still co-spends and therefore
links every input it uses. See [Mixdepth Hygiene](technical/best-practices.md#mixdepth-hygiene).

### Does PoDLE reveal one of the taker's coins?

Yes, to each maker that accepts the authentication. PoDLE makes cost-free maker
probing harder by requiring the taker to prove control of an exact UTXO before
the maker reveals its own coins. If that UTXO is then spent in the CoinJoin, the
maker can recognize it as taker-owned on chain.

The public blacklist relay contains the commitment, not the revealed outpoint,
and the proof does not reveal a real-world identity. This is a deliberate
anti-probing tradeoff. See [Privacy: PoDLE](technical/privacy.md#podle) and the
[PoDLE design note](https://gist.github.com/AdamISZ/9cbba5e9408d23813ca8).

### Can an observer tell which participant was the taker?

There is no maker or taker label on chain. Still, amount balances, assumed fees,
known protocol data, and later behavior can make one interpretation more likely:
the taker pays costs, while makers earn fees and often return liquidity to later
rounds. These are heuristics, not proof.

Repeatedly using only one role creates more behavioral information. JoinMarket
NG's tumbler can interleave maker sessions with taker transactions, but role
mixing cannot repair address reuse or careless consolidation. For deeper,
experimental analysis, see
[Making JoinMarket makers harder to follow](https://gist.github.com/m0wer/a228c625fcb6a27c32e298ec903dfc44).

### When should I use the tumbler?

Use it when the goal is a spending path, not merely one ambiguous transaction.
It spreads funds across CoinJoins, mixdepths, times, amounts, roles, and several
destinations. The defaults intentionally take time; shortening waits, removing
destinations, or disabling maker sessions trades privacy for speed.

The [tumbler guide](README-tumbler.md) explains the two-stage plan and why three
or more destinations matter.

## Beyond the Transaction

### Do I need Tor if CoinJoin already changes the transaction graph?

Yes for production JoinMarket use. CoinJoin addresses on-chain linkage, while
Tor limits network observers and directory infrastructure from tying protocol
activity to your IP address. Neither protection substitutes for the other, and
Tor does not hide mistakes made later on chain.

See [direct and relay connections](technical/protocol.md#direct-vs-relay-connections)
and the [threat model](technical/threat-model.md#network-level-identity-linkage).

### Is Lightning one giant CoinJoin?

No. Lightning uses bilateral payment channels and onion-routed payments, not a
shared transaction with a global set of interchangeable outputs. It can reduce
what is recorded on chain, but channel peers, routing nodes, public topology,
probing, timing, and channel opens or closes expose different information under
different threat models.

See
[An Empirical Analysis of Privacy in the Lightning Network](https://arxiv.org/abs/2003.12470)
and the [BOLT onion-routing specification](https://github.com/lightning/bolts/blob/master/04-onion-routing.md).

### Can an exchange reject coins that have CoinJoin history?

It can. Exchanges and other recipients set their own policies, and those
policies may be inconsistent or may change without notice. Acceptance is not a
measure of privacy, and no CoinJoin implementation can promise how a third party
will classify or handle a deposit.
