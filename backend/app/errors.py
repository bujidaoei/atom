class GatewayError(Exception):
    """The model gateway refused the call or no key is available."""


class ContractError(Exception):
    """The model reply could not be turned into a usable contract or page."""
