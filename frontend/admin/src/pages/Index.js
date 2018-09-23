import React from 'react';
import Typography from '@material-ui/core/Typography';
import Paper from '@material-ui/core/Paper';
import CssBaseline from "@material-ui/core/CssBaseline/CssBaseline";
import withStyles from "@material-ui/core/styles/withStyles";
import Grid from '@material-ui/core/Grid';

const styles = theme => ({
  title: {
    marginBottom: theme.spacing.unit * 3,
  },
  root: {
    flexGrow: 1,
  },
  paper: {
    width: '100%',
    overflowX: 'auto',
    padding: theme.spacing.unit * 4,
  },
});

function Index(props) {
  const { classes } = props;
  return (
    <React.Fragment>
      <CssBaseline />
      <div>
        <Typography className={classes.title} variant="headline">Cluster stats</Typography>
        <Grid container spacing={24}>
          <Grid item xs={12} md={4}>
            <Paper className={classes.paper}>Some graph here</Paper>
          </Grid>
          <Grid item xs={12} md={4}>
            <Paper className={classes.paper}>Some graph here</Paper>
          </Grid>
          <Grid item xs={12} md={4}>
            <Paper className={classes.paper}>Some graph here</Paper>
          </Grid>
        </Grid>
      </div>
    </React.Fragment>
  )
}

export default withStyles(styles)(Index);
