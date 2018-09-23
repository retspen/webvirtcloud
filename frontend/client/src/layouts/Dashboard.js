import React from "react";
import {Route, Switch} from "react-router-dom";
import IndexPage from "../pages/Index";
import ProfilePage from "../pages/Profile";
import Navigation from "../components/Navigation";
import withStyles from '@material-ui/core/styles/withStyles';
import CssBaseline from "@material-ui/core/CssBaseline/CssBaseline";

const styles = theme => ({
  content: {
    width: '100%',
    maxWidth: theme.breakpoints.values.md,
    margin: `${theme.spacing.unit * 4}px auto`,
    padding: `0 ${theme.spacing.unit}px`,
  }
});

function Dashboard(props) {
  const { classes } = props;
  return (
    <React.Fragment>
      <CssBaseline />
      <div className="dashboard-layout">
        <Navigation/>
        <main className={classes.content}>
          <Switch>
            <Route exact path="/" component={IndexPage}/>
            <Route path="/profile" component={ProfilePage}/>
          </Switch>
        </main>
      </div>
    </React.Fragment>
  )
}

export default withStyles(styles)(Dashboard);
