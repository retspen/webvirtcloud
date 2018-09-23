import React from 'react';
import Typography from '@material-ui/core/Typography';
import Paper from '@material-ui/core/Paper';
import Table from '@material-ui/core/Table';
import TableBody from '@material-ui/core/TableBody';
import TableCell from '@material-ui/core/TableCell';
import TableHead from '@material-ui/core/TableHead';
import TableRow from '@material-ui/core/TableRow';
import IconButton from '@material-ui/core/IconButton';
import DeleteIcon from '@material-ui/icons/Delete';
import CssBaseline from "@material-ui/core/CssBaseline/CssBaseline";
import withStyles from "@material-ui/core/styles/withStyles";

const styles = theme => ({
  title: {
    marginBottom: theme.spacing.unit * 2,
  },
  paper: {
    width: '100%',
    overflowX: 'auto',
    padding: theme.spacing.unit * 4,
  },
});

let id = 0;
function createData(name, status) {
  id += 1;
  return { id, name, status };
}

const rows = [
  createData('cloud-test', 'connected'),
  createData('cloud-ubuntu-fra3', 'disconnected'),
];

function Index(props) {
  const { classes } = props;
  return (
    <React.Fragment>
      <CssBaseline />
      <div>
        <Typography className={classes.title} variant="headline">Users</Typography>
        <Paper className={classes.paper}>
          <Table className={classes.table}>
            <TableHead>
              <TableRow>
                <TableCell>Name</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Action</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map(row => {
                return (
                  <TableRow key={row.id}>
                    <TableCell component="th" scope="row">{row.name}</TableCell>
                    <TableCell>{row.status}</TableCell>
                    <TableCell>
                      <IconButton aria-label="Delete">
                        <DeleteIcon />
                      </IconButton>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </Paper>
      </div>
    </React.Fragment>
  )
}

export default withStyles(styles)(Index);
