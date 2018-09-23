import React from "react";
import {Route, Switch} from "react-router-dom";
import SignInPage from "../pages/auth/SignIn";
import SignUpPage from "../pages/auth/SignUp";
import CssBaseline from "@material-ui/core/CssBaseline/CssBaseline";

function Auth(props) {
  return (
    <React.Fragment>
      <CssBaseline />
      <div className="dashboard-layout">
        <main>
          <Switch>
            <Route exact path="/auth/signin" component={SignInPage} />
            <Route exact path="/auth/signup" component={SignUpPage} />
          </Switch>
        </main>
      </div>
    </React.Fragment>
  )
}

export default Auth;
