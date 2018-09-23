import React, { Component } from 'react';
import { BrowserRouter as Router, Switch, Route } from 'react-router-dom';
import Dashboard from './layouts/Dashboard';
import Auth from './layouts/Auth';
import './App.css';

export default class App extends Component {
  render() {
    return (
      <Router>
        <Switch>
          <Route exact path="/" component={Dashboard} />
          <Route path="/profile" component={Dashboard} />
          <Route path="/auth" component={Auth} />
        </Switch>
      </Router>
    );
  }
}
