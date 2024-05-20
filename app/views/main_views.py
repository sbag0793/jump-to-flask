from flask import Blueprint

bp = Blueprint("main", __name__, url_prefix='/')


@bp.route('/')
def pybo_index():
    return "pybo's index."

@bp.route('/hello')
def hello_pybo():
    return "Hello, pybo! ㅋ"