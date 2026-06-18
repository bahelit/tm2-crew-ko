import logging

logger = logging.getLogger(__name__)


def plan_payout(standings, amounts):
	"""
	Pair standings with payout amounts by placement.

	:param standings:  Best-first list of standing dicts ({login, nickname, ...}).
	:param amounts:    Planet amounts by placement (index 0 = winner).
	:return:           List of ``{login, nickname, amount}`` for positive amounts.
	"""
	plan = []
	for row, amount in zip(standings, amounts):
		try:
			amount = int(amount)
		except (TypeError, ValueError):
			continue
		if amount > 0:
			plan.append(dict(login=row['login'], nickname=row.get('nickname', row['login']), amount=amount))
	return plan


async def pay_planets(instance, plan, label='Knockout cup payout'):
	"""
	Issue server Pay calls for each entry in a payout plan. Returns the list of
	entries for which the Pay call was accepted (a bill id was returned).

	Note: real planets leave the server account. Callers must gate this behind an
	explicit, admin-only opt-in.
	"""
	paid = []
	for entry in plan:
		try:
			await instance.gbx('Pay', entry['login'], entry['amount'], label)
			paid.append(entry)
			logger.info('Knockout: paid %d planets to %s (%s)',
				entry['amount'], entry['login'], label)
		except Exception as exc:
			logger.warning('Knockout: payout to %s failed: %s', entry['login'], exc)
	return paid
