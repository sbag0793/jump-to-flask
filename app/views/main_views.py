from flask import Blueprint, render_template, redirect, url_for
from app.models import Question

bp = Blueprint("main", __name__, url_prefix='/')


@bp.route('/')
def index():
  return redirect(url_for('question._list'))