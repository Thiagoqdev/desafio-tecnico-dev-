'''Exceptions raised by the indices module.'''


class IndexServiceError(Exception):
    '''Base class for indices service errors.'''


class IndexSourceUnavailable(IndexServiceError):
    '''The upstream API is temporarily unavailable.

    Triggers the cache fallback in `IndexService.get_value`.
    '''


class IndexDataUnavailable(IndexServiceError):
    '''No value is available — neither in cache nor from the upstream API.'''


class IndexTypeNotFound(IndexServiceError):
    '''No `IndexType` row exists with the requested code.'''
