"""Sous-ensemble minimal de FastAPI pour la version autonome de borgHelperWWW (stdlib seule) : FastAPI, APIRouter,
Header, Query, Depends, HTTPException, Request, injection des paramètres, validation (réponses 422 au format de
FastAPI 0.63 / pydantic 1), response_model, /openapi.json et /docs. Comportement aligné sur FastAPI 0.63."""
__version__ = "0.63.0-borgHelperWWW-autonome"

from starlette.requests import Request
from starlette.responses import Response

from fastapi.applications import FastAPI
from fastapi.exceptions import HTTPException
from fastapi.params import Body, Cookie, Depends, Header, Path, Query
from fastapi.routing import APIRouter

__all__ = ["FastAPI", "APIRouter", "HTTPException", "Request", "Response", "Header", "Query", "Depends", "Body",
           "Cookie", "Path"]
